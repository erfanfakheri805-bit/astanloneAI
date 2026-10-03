"""
Learned Knowledge Decision Statistics
========================================
Prompt 504. A small, diagnostic-only aggregation layer over the
Prompt 503 decision traces (learning/learned_knowledge_gate.py -
`LearnedKnowledgeGateTrace` / `build_learned_knowledge_gate_trace()`):

    [LearnedKnowledgeGateTrace, ...] -> summarize_learned_knowledge_decisions()
                                          -> plain summary dict
    LearnedKnowledgeDecisionStatistics().record(trace)  (repeatable)
                                          .summary() -> the same summary dict

This follows the exact same "small, stateless summarizer over a batch
of already-computed results" shape `LearningAnalyzer.analyze()` /
`analyze_store()` already use for `LearningRecord`s (learning/
learning_analyzer.py) - a `LearnedKnowledgeDecisionStatistics` is to
decision traces what a `LearningRecordStore` + `LearningAnalyzer` pair
is to learning records, kept small enough not to need two classes.

What this is
------------
Purely descriptive counting over traces the caller already has (or
hands it one at a time via `record()`). It reads each trace's own
`decision` field - already fixed by Prompt 503 from Prompt 502's
verdict - and tallies it. Nothing here re-evaluates relevance or
reliability, calls `LearningAnalyzer` or the gate, mutates the trace
it is given, or touches any learned record, `LearningRecordStore`, or
`KnowledgeSystem` entry. `record()` only appends to this object's own
internal count; the trace object itself, and whatever produced it, are
left exactly as they were.

What this is not
-----------------
Not a second decision, reliability, or learning system: every count
here is a straight readout of a `decision` value the Prompt 502/503
pipeline already produced. It has no effect on any response, and it
does not change what a future evaluation will decide - it only counts
what already happened. Nothing here is inserted into a user-facing
response (Prompt 504 keeps this internal-only, same as Prompt 503).

Rates are calculated safely: with zero recorded evaluations, both
rates are `0.0` and every count is `0` - never a division by zero.
"""

import copy
import math

from .learned_knowledge_gate import (
    DECISION_ACCEPTED,
    DECISION_REJECTED_IRRELEVANT,
    DECISION_REJECTED_LOW_RELIABILITY,
    DECISION_REJECTED_INSUFFICIENT_EVIDENCE,
    DECISION_NO_CANDIDATE,
    DECISION_GATE_ERROR,
)

# The three rejection_reasons buckets the gate can produce for a
# candidate it actually evaluated (excludes NO_CANDIDATE, which is
# tracked as its own top-level count, not a rejection reason).
_REJECTION_DECISIONS = (
    DECISION_REJECTED_IRRELEVANT,
    DECISION_REJECTED_LOW_RELIABILITY,
    DECISION_REJECTED_INSUFFICIENT_EVIDENCE,
)

_EMPTY_REJECTION_REASONS = {decision: 0 for decision in _REJECTION_DECISIONS}


def _decision_of(trace):
    """The `decision` value of `trace` - a `LearnedKnowledgeGateTrace`,
    its `to_dict()`, or anything else (which simply has no decision).
    Never raises."""
    if hasattr(trace, "decision"):
        return getattr(trace, "decision")
    if isinstance(trace, dict):
        return trace.get("decision")
    return None


def _safe_rate(numerator, denominator):
    return numerator / denominator if denominator else 0.0


class LearnedKnowledgeDecisionStatistics:
    """Stateful counter over decision traces, `record()`ed one at a
    time as `Core._attach_learned_knowledge()` produces them - the
    running equivalent of calling `summarize_learned_knowledge_decisions()`
    on every trace seen so far. Holds only plain integers; never stores
    a trace, a learned record, or anything from `selection`/`message`."""

    def __init__(self):
        self._total_evaluations = 0
        self._total_accepted = 0
        self._total_no_candidate = 0
        self._total_gate_errors = 0
        self._rejection_reasons = dict(_EMPTY_REJECTION_REASONS)

    def record(self, trace):
        """Tally one trace. Ignores anything with no recognizable
        `decision` (e.g. `None`, a malformed value) rather than
        raising - same "ignore what's invalid" convention
        `LearningAnalyzer.analyze()` already follows. Never mutates
        `trace`; returns nothing."""
        decision = _decision_of(trace)
        if decision == DECISION_ACCEPTED:
            self._total_accepted += 1
        elif decision == DECISION_NO_CANDIDATE:
            self._total_no_candidate += 1
        elif decision == DECISION_GATE_ERROR:
            self._total_gate_errors += 1
        elif decision in self._rejection_reasons:
            self._rejection_reasons[decision] += 1
        else:
            # None, or a decision string this statistics layer doesn't
            # recognize - not counted anywhere (same "ignore what's
            # invalid rather than fail the whole calculation" convention
            # LearningAnalyzer.analyze() already follows).
            return
        self._total_evaluations += 1

    def summary(self):
        """The current counts/rates as a plain dict - see
        `summarize_learned_knowledge_decisions()` for the exact shape.
        Safe to call at any time, including with zero recorded
        evaluations. Never mutates this object's own counters."""
        total_rejected = sum(self._rejection_reasons.values())
        total = self._total_evaluations
        return {
            "total_evaluations": total,
            "total_accepted": self._total_accepted,
            "total_rejected": total_rejected,
            "total_no_candidate": self._total_no_candidate,
            "total_gate_errors": self._total_gate_errors,
            "rejection_reasons": dict(self._rejection_reasons),
            "acceptance_rate": _safe_rate(self._total_accepted, total),
            "rejection_rate": _safe_rate(total_rejected, total),
        }

    def reset(self):
        """Zero every counter - a fresh `LearnedKnowledgeDecisionStatistics()`
        in place. Provided for callers (e.g. tests) that want a clean
        slate without constructing a new instance; never touches any
        trace, learned record, or gate/response behavior."""
        self.__init__()

    def analyze(self):
        """Convenience wrapper: `analyze_learned_knowledge_statistics(self)`.
        See that function for the returned shape and guarantees. Reads
        `self.summary()`; never mutates this object's own counters."""
        return analyze_learned_knowledge_statistics(self)

    def validate_analysis(self):
        """Convenience wrapper: `validate_learned_knowledge_statistics_analysis(self.analyze())`.
        See that function for the returned shape and guarantees. Never
        mutates this object's own counters."""
        return validate_learned_knowledge_statistics_analysis(self.analyze())

    def summarize_analysis(self):
        """Convenience wrapper: analyzes and validates this object's
        current counts (via `self.analyze()` / `self.validate_analysis()`,
        unchanged), then builds the Prompt 507
        `build_learned_knowledge_analysis_summary()` summary from that
        exact pair. See that function for the returned shape and
        guarantees. Never mutates this object's own counters."""
        analysis = self.analyze()
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        return build_learned_knowledge_analysis_summary(analysis, validation)


_EMPTY_ANALYSIS = {
    "total_evaluations": 0,
    "accepted_count": 0,
    "rejected_count": 0,
    "no_candidate_count": 0,
    "acceptance_rate": 0.0,
    "rejection_rate": 0.0,
    "dominant_rejection_reason": None,
}


def _summary_of(statistics):
    """The Prompt 504 summary dict for `statistics` - a
    `LearnedKnowledgeDecisionStatistics` instance, or a summary dict
    already produced by `.summary()` / `summarize_learned_knowledge_decisions()`.
    Never mutates `statistics`; never raises for something else (falls
    back to the all-zero summary shape via a fresh, untouched
    `LearnedKnowledgeDecisionStatistics()`)."""
    if isinstance(statistics, LearnedKnowledgeDecisionStatistics):
        return statistics.summary()
    if isinstance(statistics, dict):
        return statistics
    return LearnedKnowledgeDecisionStatistics().summary()


def _dominant_rejection_reason(rejection_reasons):
    """The rejection reason with the highest count, or `None` when
    there are no rejections at all (every count is `0`, or the dict is
    empty). Deterministic on ties: iterates `_REJECTION_DECISIONS` in
    its fixed declaration order (irrelevant, then low_reliability, then
    insufficient_evidence) and keeps the first reason whose count is
    strictly greater than the best seen so far - so a tie always
    resolves to whichever of the tied reasons comes first in that
    fixed order, the same way on every call. Never mutates
    `rejection_reasons`."""
    best_decision = None
    best_count = 0
    for decision in _REJECTION_DECISIONS:
        count = rejection_reasons.get(decision, 0)
        if count > best_count:
            best_count = count
            best_decision = decision
    return best_decision


def analyze_learned_knowledge_statistics(statistics):
    """Deterministic, read-only diagnostic analysis over Prompt 504's
    own statistics - accepts a `LearnedKnowledgeDecisionStatistics`
    instance or a summary dict (`.summary()` /
    `summarize_learned_knowledge_decisions()`'s return value) and
    returns a new, independent structured summary dict:

        {
            "total_evaluations": <int>,
            "accepted_count": <int>,
            "rejected_count": <int>,
            "no_candidate_count": <int>,
            "acceptance_rate": <float>,
            "rejection_rate": <float>,
            "dominant_rejection_reason": <str or None>,
        }

    This is strictly descriptive: every field is a direct readout of
    (or a simple derivation from) the Prompt 504 statistics structure
    already reused via `_summary_of()` - nothing here recomputes
    candidate relevance or reliability, re-runs the gate, or touches
    any trace, learned record, threshold, or response. Calling this
    never mutates `statistics` (a dict argument is read, not written;
    a `LearnedKnowledgeDecisionStatistics` argument only has its own
    `summary()` called, which itself makes no changes - see that
    method's docstring). `dominant_rejection_reason` is `None` when
    there are no rejected decisions; see `_dominant_rejection_reason()`
    for how ties between rejection reasons are broken deterministically.
    `total_evaluations == 0` (including `statistics=None` or anything
    unrecognized) safely yields the same all-zero/`None` empty-state
    result every time.

    This analysis is diagnostic-only: it does not interpret the counts
    as evidence that the system is or isn't working correctly, is not
    wired into response generation, and is not exposed to normal
    user-facing responses.
    """
    summary = _summary_of(statistics)
    total = summary.get("total_evaluations", 0) or 0
    if not total:
        return dict(_EMPTY_ANALYSIS)

    accepted = summary.get("total_accepted", 0)
    rejected = summary.get("total_rejected", 0)
    no_candidate = summary.get("total_no_candidate", 0)
    rejection_reasons = summary.get("rejection_reasons", {}) or {}

    return {
        "total_evaluations": total,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "no_candidate_count": no_candidate,
        "acceptance_rate": summary.get("acceptance_rate", _safe_rate(accepted, total)),
        "rejection_rate": summary.get("rejection_rate", _safe_rate(rejected, total)),
        "dominant_rejection_reason": _dominant_rejection_reason(rejection_reasons),
    }


def summarize_learned_knowledge_decisions(traces):
    """The summary dict for `traces` (an iterable of
    `LearnedKnowledgeGateTrace` objects and/or their `to_dict()`s) in
    one call - the batch equivalent of feeding each one to a fresh
    `LearnedKnowledgeDecisionStatistics().record()`. `traces=None` or
    an empty/all-unrecognized iterable both yield the same
    all-zero summary `LearnedKnowledgeDecisionStatistics().summary()`
    does. Never raises, never mutates any trace.

    Shape:
        {
            "total_evaluations": <int>,
            "total_accepted": <int>,
            "total_rejected": <int>,
            "total_no_candidate": <int>,
            "total_gate_errors": <int>,
            "rejection_reasons": {
                "rejected_irrelevant": <int>,
                "rejected_low_reliability": <int>,
                "rejected_insufficient_evidence": <int>,
            },
            "acceptance_rate": <float>,     # total_accepted / total_evaluations
            "rejection_rate": <float>,      # total_rejected / total_evaluations
        }
    """
    stats = LearnedKnowledgeDecisionStatistics()
    for trace in traces or []:
        stats.record(trace)
    return stats.summary()


# ----------------------------------------------------------------------
# Prompt 506 - validation of a Prompt 505 analysis result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check over the dict
# `analyze_learned_knowledge_statistics()` (Prompt 505) returns. There
# is no existing validator/schema-validator/diagnostics-validator for
# this analysis shape anywhere in the project (the nearest relatives -
# `language_intelligence/correction_application_result_validation.py`
# and friends - validate a different, unrelated result type), so this
# adds one small function rather than reusing/extending an unrelated
# validator. It does not re-derive the analysis from raw traces/
# statistics, does not repair or reinterpret anything it finds wrong,
# and never mutates the `analysis` dict it is given.

_ANALYSIS_COUNT_FIELDS = (
    "total_evaluations",
    "accepted_count",
    "rejected_count",
    "no_candidate_count",
)
_ANALYSIS_RATE_FIELDS = ("acceptance_rate", "rejection_rate")
_ANALYSIS_REQUIRED_FIELDS = _ANALYSIS_COUNT_FIELDS + _ANALYSIS_RATE_FIELDS + (
    "dominant_rejection_reason",
)

# Tolerance for comparing a rate already stored as a float against one
# recomputed here from the analysis's own counts - purely to absorb
# ordinary floating-point representation error, not to allow any real
# disagreement between the two.
_RATE_TOLERANCE = 1e-9


def _is_plain_number(value):
    """True for an `int` or `float` that isn't secretly a `bool`
    (`bool` is a subclass of `int` in Python, but `True`/`False` are
    never valid counts or rates here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_plain_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_learned_knowledge_statistics_analysis(analysis):
    """Deterministic, read-only structural validation of `analysis` -
    the dict shape returned by `analyze_learned_knowledge_statistics()`
    (Prompt 505) or `LearnedKnowledgeDecisionStatistics.analyze()`.
    Returns a new, independent plain dict:

        {
            "valid": <bool>,
            "errors": [<str>, ...],
            "warnings": [<str>, ...],
        }

    `valid` is `True` exactly when `errors` is empty; `warnings` is
    always a list (empty when there is nothing to flag) so callers
    have a stable shape to read regardless of outcome.

    What is checked
    ----------------
    - every field in `_ANALYSIS_REQUIRED_FIELDS` is present
      (`"missing_field:<name>"` otherwise)
    - each of `_ANALYSIS_COUNT_FIELDS` is a non-negative `int`
      (`"invalid_count_type:<name>"` / `"negative_count:<name>"`)
    - each of `_ANALYSIS_RATE_FIELDS` is a plain number in `[0.0, 1.0]`
      (`"invalid_rate_type:<name>"` / `"rate_below_valid_range:<name>"`
      / `"rate_above_valid_range:<name>"`)
    - `dominant_rejection_reason` is `None` or one of the existing
      `_REJECTION_DECISIONS` (`"invalid_dominant_rejection_reason"`)
    - when the relevant fields above are themselves individually
      valid, three Prompt 504/505-consistent relationships:
        - `accepted_count + rejected_count + no_candidate_count` does
          not exceed `total_evaluations` (Prompt 504's own `record()`
          also counts `DECISION_GATE_ERROR` towards
          `total_evaluations`, which Prompt 505's analysis does not
          expose as its own field, so equality is not assumed here -
          only that the exposed counts cannot add up to more than the
          recorded total: `"counts_exceed_total_evaluations"`)
        - `acceptance_rate` equals `accepted_count / total_evaluations`
          under Prompt 504's own zero-safe division
          (`"inconsistent_acceptance_rate"`)
        - `rejection_rate` equals `rejected_count / total_evaluations`
          the same way (`"inconsistent_rejection_rate"`)
      A field that already failed its own type/range/missing check is
      left out of these relationship checks (there is nothing
      meaningful to compare against), so a single bad field never
      cascades into extra, misleading consistency errors.

    Never repairs, reinterprets, or otherwise changes `analysis` -
    every problem found is reported, not fixed. Never mutates
    `analysis`, whatever it turns out to be (a non-dict `analysis`,
    including `None`, safely produces a single
    `"analysis_not_a_dict"` error rather than raising). Never touches
    the statistics, traces, or learned records `analysis` was computed
    from, is not called anywhere in the gate/decision/response path,
    and does not itself decide whether learned knowledge is accepted
    or rejected - purely descriptive, same as
    `analyze_learned_knowledge_statistics()` itself. Deterministic:
    the same `analysis` dict always produces an equal validation
    result, in the same order, on every call.
    """
    if not isinstance(analysis, dict):
        return {"valid": False, "errors": ["analysis_not_a_dict"], "warnings": []}

    errors = []
    warnings = []

    for field in _ANALYSIS_REQUIRED_FIELDS:
        if field not in analysis:
            errors.append("missing_field:%s" % field)

    valid_counts = {}
    for field in _ANALYSIS_COUNT_FIELDS:
        if field not in analysis:
            continue
        value = analysis[field]
        if not _is_plain_int(value):
            errors.append("invalid_count_type:%s" % field)
        elif value < 0:
            errors.append("negative_count:%s" % field)
        else:
            valid_counts[field] = value

    valid_rates = {}
    for field in _ANALYSIS_RATE_FIELDS:
        if field not in analysis:
            continue
        value = analysis[field]
        if not _is_plain_number(value):
            errors.append("invalid_rate_type:%s" % field)
        elif value < 0.0:
            errors.append("rate_below_valid_range:%s" % field)
        elif value > 1.0:
            errors.append("rate_above_valid_range:%s" % field)
        else:
            valid_rates[field] = float(value)

    if "dominant_rejection_reason" in analysis:
        reason = analysis["dominant_rejection_reason"]
        if reason is not None and reason not in _REJECTION_DECISIONS:
            errors.append("invalid_dominant_rejection_reason")

    if "total_evaluations" in valid_counts:
        total = valid_counts["total_evaluations"]
        component_fields = [
            field for field in ("accepted_count", "rejected_count", "no_candidate_count")
            if field in valid_counts
        ]
        if len(component_fields) == 3:
            component_sum = sum(valid_counts[field] for field in component_fields)
            if component_sum > total:
                errors.append("counts_exceed_total_evaluations")

        if "accepted_count" in valid_counts and "acceptance_rate" in valid_rates:
            expected = _safe_rate(valid_counts["accepted_count"], total)
            if not math.isclose(valid_rates["acceptance_rate"], expected,
                                 rel_tol=_RATE_TOLERANCE, abs_tol=_RATE_TOLERANCE):
                errors.append("inconsistent_acceptance_rate")

        if "rejected_count" in valid_counts and "rejection_rate" in valid_rates:
            expected = _safe_rate(valid_counts["rejected_count"], total)
            if not math.isclose(valid_rates["rejection_rate"], expected,
                                 rel_tol=_RATE_TOLERANCE, abs_tol=_RATE_TOLERANCE):
                errors.append("inconsistent_rejection_rate")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


# ----------------------------------------------------------------------
# Prompt 507 - human-readable summary of a validated Prompt 505/506 result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY diagnostic helper that turns an
# already-computed Prompt 505 analysis dict plus its already-computed
# Prompt 506 validation dict into one more plain dict - the same
# fields, unchanged, plus a short human-readable `"text"` line. This
# is not a third statistics/validation system: it performs no counting
# of its own (that is `LearnedKnowledgeDecisionStatistics`/
# `analyze_learned_knowledge_statistics`, Prompt 504/505) and no
# structural checking of its own (that is
# `validate_learned_knowledge_statistics_analysis`, Prompt 506) - it
# only reads the two dicts it is handed and formats what they already
# say. Nothing here re-evaluates relevance/reliability, recomputes a
# validation verdict, or mutates `analysis` or `validation`.

_INVALID_VALIDATION_TEXT = (
    "Learned knowledge analysis summary unavailable: the provided "
    "validation result is not a recognized Prompt 506 validation result."
)
_INVALID_ANALYSIS_TEXT = (
    "Learned knowledge analysis summary unavailable: the provided "
    "analysis result is not a recognized dict."
)


def _errors_text(errors):
    return ", ".join(errors) if errors else "(none reported)"


def build_learned_knowledge_analysis_summary(analysis, validation):
    """Build a plain dict summarizing `analysis` (a Prompt 505
    `analyze_learned_knowledge_statistics()` result) using its own
    already-computed `validation` (a Prompt 506
    `validate_learned_knowledge_statistics_analysis(analysis)` result)
    to decide whether it is safe to describe.

    When `validation["valid"]` is not `True` (or `validation` itself
    isn't a recognizable Prompt 506 validation dict), this NEVER
    inspects `analysis`'s individual fields, never guesses or invents
    values for them, and never proceeds as though `analysis` were
    valid - it returns exactly:

        {
            "valid": False,
            "errors": [<the validation's own "errors", unchanged>],
            "text": "<short human-readable statement that the result
                      is invalid, listing those same errors>",
        }

    When `validation["valid"]` is `True`, returns:

        {
            "valid": True,
            "errors": [],
            "total_evaluations": <int, straight from analysis>,
            "accepted_count": <int, straight from analysis>,
            "rejected_count": <int, straight from analysis>,
            "no_candidate_count": <int, straight from analysis>,
            "acceptance_rate": <float, straight from analysis>,
            "rejection_rate": <float, straight from analysis>,
            "dominant_rejection_reason": <str or None, straight from analysis>,
            "text": "<short human-readable one-or-two-sentence summary
                      of the counts/rates/dominant reason above>",
        }

    Every non-text field above is copied from `analysis` unchanged -
    nothing is recalculated, reinterpreted, or rounded (the `"text"`
    line does round rates for display, but the structured fields
    alongside it are exact). Deterministic: the same `analysis` and
    `validation` always produce an equal summary dict. Never mutates
    `analysis` or `validation`, never touches the underlying
    statistics, traces, or learned records, is not wired into the
    gate/decision/response path, and is not exposed to normal
    user-facing responses (same "internal, diagnostic-only" posture as
    Prompt 504/505/506).
    """
    if not isinstance(validation, dict) or "valid" not in validation:
        errors = (
            list(validation.get("errors", []))
            if isinstance(validation, dict) else ["validation_not_a_dict"]
        )
        return {"valid": False, "errors": errors, "text": _INVALID_VALIDATION_TEXT}

    if not validation.get("valid", False):
        errors = list(validation.get("errors", []))
        return {
            "valid": False,
            "errors": errors,
            "text": "Learned knowledge analysis result is INVALID. "
                    "Validation errors: " + _errors_text(errors),
        }

    if not isinstance(analysis, dict):
        return {"valid": False, "errors": ["analysis_not_a_dict"], "text": _INVALID_ANALYSIS_TEXT}

    total = analysis.get("total_evaluations")
    accepted = analysis.get("accepted_count")
    rejected = analysis.get("rejected_count")
    no_candidate = analysis.get("no_candidate_count")
    acceptance_rate = analysis.get("acceptance_rate")
    rejection_rate = analysis.get("rejection_rate")
    dominant = analysis.get("dominant_rejection_reason")

    if not total:
        text = "Learned knowledge analysis: no evaluations recorded yet."
    else:
        text = (
            "Learned knowledge analysis: {total} evaluation(s) - "
            "{accepted} accepted ({acceptance_rate:.0%}), "
            "{rejected} rejected ({rejection_rate:.0%}), "
            "{no_candidate} with no candidate."
        ).format(
            total=total, accepted=accepted, acceptance_rate=acceptance_rate or 0.0,
            rejected=rejected, rejection_rate=rejection_rate or 0.0,
            no_candidate=no_candidate,
        )
        if dominant is not None:
            text += " Dominant rejection reason: {0}.".format(dominant)
        else:
            text += " No dominant rejection reason (no rejected decisions)."

    return {
        "valid": True,
        "errors": [],
        "total_evaluations": total,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "no_candidate_count": no_candidate,
        "acceptance_rate": acceptance_rate,
        "rejection_rate": rejection_rate,
        "dominant_rejection_reason": dominant,
        "text": text,
    }


# ----------------------------------------------------------------------
# Prompt 508 - bounded snapshot history of the Prompt 505/506/507 diagnostics
# ----------------------------------------------------------------------
# A small, in-memory, diagnostic-only record of point-in-time snapshots of
# the structured diagnostic information Prompts 504-507 already produce,
# so a future component can compare how the learned-knowledge pipeline
# behaved over time.
#
# Architecture reuse: the project has no existing diagnostics/metrics/
# snapshot history. The two nearest histories (`planning/proposal_history.
# ProposalHistory`, `financial/revenue_task_result_history.
# RevenueTaskResultHistory`) only accept their own, unrelated record types
# and are unbounded, so neither can hold these snapshots. This class
# therefore follows their shared convention (in-memory only, insertion-
# order list, `copy.deepcopy` in and out, `get_all`/`get_latest`-style
# retrieval, `[]`/`None` for "nothing there") and lives next to the
# Prompt 504-507 code it snapshots, rather than becoming a second
# memory/persistence system.
#
# Each snapshot is built from the Prompt 507 summary
# (`build_learned_knowledge_analysis_summary()`), so an invalid analysis is
# handled exactly as Prompt 507 handles it: the analysis's own fields are
# never inspected or guessed at, and the snapshot's count/rate/reason
# fields are `None`.
#
# Nothing here reads or writes a trace, a learned record, the
# `LearnedKnowledgeDecisionStatistics` counters, a threshold, the gate, or
# any response path. Nothing calls `record()` automatically and nothing
# ever reads this history to make a decision.

# Fixed capacity: once this many snapshots are held, recording another
# drops ONLY the single oldest one (first-in-first-out), the same way
# every time - the newest snapshots are always the ones kept. No other
# snapshot is ever removed. `snapshot_id`/`sequence` numbers are never
# reused after an eviction, so a gap at the start of the sequence is the
# visible sign of an evicted snapshot. Overridable per instance via
# `LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=N)`.
DEFAULT_MAX_SNAPSHOT_HISTORY = 100

SNAPSHOT_VALIDATION_VALID = "valid"
SNAPSHOT_VALIDATION_INVALID = "invalid"

_SNAPSHOT_ID_FORMAT = "learned_knowledge_snapshot_%06d"

# Fixed field order of every snapshot (same keys on every snapshot, valid
# or invalid - a stable shape for comparison).
_SNAPSHOT_ANALYSIS_FIELDS = (
    "total_evaluations",
    "accepted_count",
    "rejected_count",
    "no_candidate_count",
    "acceptance_rate",
    "rejection_rate",
    "dominant_rejection_reason",
)


class _BoundedDiagnosticSnapshotStore:
    """The bounded, in-memory, oldest-first snapshot storage Prompt 508
    introduced, moved here unchanged (Prompt 517) so it can be shared by
    `LearnedKnowledgeDiagnosticSnapshotHistory` (Prompt 508 analysis
    snapshots) and `LearnedKnowledgeFilteredSummarySnapshotHistory`
    (Prompt 517 filtered-summary snapshots) without copying its
    retention, sequence, or retrieval logic. It stores whatever snapshot
    dicts (each with a `"sequence"`) its subclass hands to
    `_store_snapshot()`; it knows nothing about their content.

    Being a separate base rather than a subclass relationship keeps
    `isinstance(x, LearnedKnowledgeDiagnosticSnapshotHistory)` - which
    the Prompt 513/514 report code uses - true only for a real Prompt 508
    history.
    """

    def __init__(self, max_snapshots=DEFAULT_MAX_SNAPSHOT_HISTORY):
        if not _is_plain_int(max_snapshots) or max_snapshots < 1:
            max_snapshots = DEFAULT_MAX_SNAPSHOT_HISTORY
        self._max_snapshots = max_snapshots
        self._snapshots = []
        self._next_sequence = 1

    @property
    def max_snapshots(self):
        return self._max_snapshots

    def __len__(self):
        return len(self._snapshots)

    def _store_snapshot(self, snapshot):
        """Store a deep copy of `snapshot` as the newest entry, advance the
        never-reused sequence counter, evict ONLY the single oldest entry
        when over capacity, and return a fresh copy of what was stored.
        The one place this history's bounded retention lives (Prompt 508);
        Prompt 517's filtered-summary history reuses it."""
        snapshot = copy.deepcopy(snapshot)

        self._next_sequence += 1
        self._snapshots.append(snapshot)
        if len(self._snapshots) > self._max_snapshots:
            del self._snapshots[0]
        return copy.deepcopy(snapshot)

    # ------------------------------------------------------------------
    # Retrieval (always fresh copies; never mutates stored snapshots)
    # ------------------------------------------------------------------
    def get_all(self):
        """Every held snapshot, oldest-first. `[]` when empty."""
        return [copy.deepcopy(snapshot) for snapshot in self._snapshots]

    def get_latest(self):
        """The most recently recorded snapshot, or `None` when empty."""
        return copy.deepcopy(self._snapshots[-1]) if self._snapshots else None

    def get_recent(self, limit=None):
        """The most recent `limit` snapshots, still oldest-first. `None`
        returns every held snapshot; a positive int returns up to that
        many; zero, a negative number, or a non-int returns `[]`.
        `[]` when empty."""
        if limit is None:
            return self.get_all()
        if not _is_plain_int(limit) or limit < 1:
            return []
        return [copy.deepcopy(snapshot) for snapshot in self._snapshots[-limit:]]

    def _copy_of_sequence(self, sequence):
        """A fresh copy of the held snapshot whose `sequence` is
        `sequence`, or `None` when there is none (unknown, evicted,
        non-int). Never mutates the history."""
        if not _is_plain_int(sequence):
            return None
        for snapshot in self._snapshots:
            if snapshot["sequence"] == sequence:
                return copy.deepcopy(snapshot)
        return None


class LearnedKnowledgeDiagnosticSnapshotHistory(_BoundedDiagnosticSnapshotStore):
    """Bounded, in-memory, oldest-first history of diagnostic snapshots.

    A snapshot is a plain dict, always with exactly these keys:

        {
            "snapshot_id": "learned_knowledge_snapshot_000001",
            "sequence": 1,                       # 1-based, increasing, never reused
            "validation_status": "valid" | "invalid",
            "validation_errors": [<str>, ...],   # the Prompt 506 errors, unchanged
            "total_evaluations": <int or None>,
            "accepted_count": <int or None>,
            "rejected_count": <int or None>,
            "no_candidate_count": <int or None>,
            "acceptance_rate": <float or None>,
            "rejection_rate": <float or None>,
            "dominant_rejection_reason": <str or None>,
        }

    The analysis fields are `None` when `validation_status` is
    `"invalid"` (they were never trustworthy - see the Prompt 507
    summary this is built from). No timestamps, raw user text, traces,
    or learned records are ever stored, so a snapshot is a pure function
    of its inputs and the sequence number.

    Isolation: `record()` stores a deep copy built from the inputs, and
    every retrieval returns fresh deep copies, so changing the original
    analysis/validation/statistics - or anything a caller got back -
    never changes what this history holds.

    Not thread-safe (same as the rest of this project's histories).
    """

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(self, analysis, validation):
        """Store a snapshot of `analysis` (a Prompt 505 result) as judged
        by its own `validation` (a Prompt 506 result) and return a copy
        of what was stored. Never raises for unrecognized input (it
        becomes an `"invalid"` snapshot, per Prompt 507) and never
        mutates `analysis` or `validation`."""
        summary = build_learned_knowledge_analysis_summary(analysis, validation)
        is_valid = summary.get("valid") is True
        sequence = self._next_sequence
        snapshot = {
            "snapshot_id": _SNAPSHOT_ID_FORMAT % sequence,
            "sequence": sequence,
            "validation_status": (
                SNAPSHOT_VALIDATION_VALID if is_valid else SNAPSHOT_VALIDATION_INVALID
            ),
            "validation_errors": list(summary.get("errors", [])),
        }
        for field in _SNAPSHOT_ANALYSIS_FIELDS:
            snapshot[field] = summary.get(field) if is_valid else None
        return self._store_snapshot(snapshot)

    def record_statistics(self, statistics):
        """Convenience: analyze (Prompt 505) and validate (Prompt 506)
        `statistics` - a `LearnedKnowledgeDecisionStatistics` or a
        summary dict - then `record()` that pair. Reads `statistics`
        only through the existing read-only functions."""
        analysis = analyze_learned_knowledge_statistics(statistics)
        validation = validate_learned_knowledge_statistics_analysis(analysis)
        return self.record(analysis, validation)

    # ------------------------------------------------------------------
    # Prompt 509 - read-only comparison of two stored snapshots
    # ------------------------------------------------------------------
    def compare_sequences(self, earlier_sequence, later_sequence):
        """`compare_learned_knowledge_diagnostic_snapshots()` applied to
        the held snapshots with those two sequence numbers -
        `earlier_sequence` is the baseline, `later_sequence` the
        current one, in the order given. A sequence with no held
        snapshot is treated as a missing snapshot (an invalid
        comparison result, never an exception). Read-only: this
        history is left exactly as it was."""
        return compare_learned_knowledge_diagnostic_snapshots(
            self._copy_of_sequence(earlier_sequence), self._copy_of_sequence(later_sequence))

    def compare_latest(self):
        """Compares the second-most-recent held snapshot (baseline)
        with the most recent one (current). With fewer than two held
        snapshots the missing one is reported as such (an invalid
        comparison result, never an exception). Read-only."""
        count = len(self._snapshots)
        earlier = copy.deepcopy(self._snapshots[-2]) if count >= 2 else None
        later = copy.deepcopy(self._snapshots[-1]) if count >= 1 else None
        return compare_learned_knowledge_diagnostic_snapshots(earlier, later)


# ----------------------------------------------------------------------
# Prompt 509 - comparison of two Prompt 508 diagnostic snapshots
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY function over two snapshot dicts
# (as stored by `LearnedKnowledgeDiagnosticSnapshotHistory`). There is no
# existing comparison/diff utility for this data anywhere in the project
# (the only "compare" helper, `agent/code_correction_retest.
# compare_test_outcomes`, is about an unrelated test-outcome type), so
# this adds one function next to the snapshot history it reads instead of
# a second snapshot/statistics system. It performs no counting of its own,
# does not re-evaluate any learned-knowledge relevance/reliability, and
# never repairs, guesses or fills in a value. It mutates nothing it is
# given, is not called anywhere in the gate/decision/response path, and
# nothing reads its result to change any behavior or threshold.

COMPARISON_DIRECTION = "later_minus_earlier"

CHANGE_UNCHANGED = "unchanged"
CHANGE_CHANGED = "changed"
CHANGE_BECAME_EMPTY = "became_empty"
CHANGE_BECAME_AVAILABLE = "became_available"
CHANGE_NOT_COMPARABLE = "not_comparable"

_SNAPSHOT_NUMERIC_FIELDS = _ANALYSIS_COUNT_FIELDS + _ANALYSIS_RATE_FIELDS
_SNAPSHOT_REQUIRED_FIELDS = (
    "snapshot_id", "sequence", "validation_status", "validation_errors",
) + _SNAPSHOT_ANALYSIS_FIELDS
_SNAPSHOT_STATUSES = (SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID)


def _snapshot_structural_errors(snapshot):
    """Structural problems with `snapshot` as a Prompt 508 snapshot, as
    an ordered list of short codes (empty when it is well-formed).
    A snapshot whose own `validation_status` is `"invalid"` is still a
    well-formed snapshot - it just carries no analysis values (all
    `None`), exactly as `record()` stores it. For a `"valid"` snapshot
    the analysis fields are checked with the existing Prompt 506
    validator (its errors are reported with an `"analysis:"` prefix).
    Never mutates `snapshot`; never raises."""
    if snapshot is None:
        return ["snapshot_missing"]
    if not isinstance(snapshot, dict):
        return ["snapshot_not_a_dict"]

    errors = []
    for field in _SNAPSHOT_REQUIRED_FIELDS:
        if field not in snapshot:
            errors.append("missing_field:%s" % field)

    if "snapshot_id" in snapshot:
        snapshot_id = snapshot["snapshot_id"]
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            errors.append("invalid_snapshot_id")
    if "sequence" in snapshot:
        sequence = snapshot["sequence"]
        if not _is_plain_int(sequence) or sequence < 1:
            errors.append("invalid_sequence")

    status = None
    if "validation_status" in snapshot:
        if snapshot["validation_status"] in _SNAPSHOT_STATUSES:
            status = snapshot["validation_status"]
        else:
            errors.append("invalid_validation_status")
    if "validation_errors" in snapshot:
        validation_errors = snapshot["validation_errors"]
        if (not isinstance(validation_errors, list)
                or not all(isinstance(item, str) for item in validation_errors)):
            errors.append("invalid_validation_errors")
        elif status == SNAPSHOT_VALIDATION_VALID and validation_errors:
            errors.append("valid_snapshot_has_validation_errors")

    if status == SNAPSHOT_VALIDATION_VALID:
        if all(field in snapshot for field in _SNAPSHOT_ANALYSIS_FIELDS):
            analysis = {field: snapshot[field] for field in _SNAPSHOT_ANALYSIS_FIELDS}
            for error in validate_learned_knowledge_statistics_analysis(analysis)["errors"]:
                errors.append("analysis:" + error)
    elif status == SNAPSHOT_VALIDATION_INVALID:
        for field in _SNAPSHOT_ANALYSIS_FIELDS:
            if field in snapshot and snapshot[field] is not None:
                errors.append("invalid_snapshot_has_analysis_field:%s" % field)
    return errors


def _snapshot_validation_information(snapshot):
    """Whatever of `snapshot`'s own validation information is usable, as
    `{"validation_status": <str or None>, "validation_errors": <list or
    None>}`, or `None` when `snapshot` is not a dict. Nothing is
    invented: an unusable part is `None`."""
    if not isinstance(snapshot, dict):
        return None
    status = snapshot.get("validation_status")
    if not isinstance(status, str) or status not in _SNAPSHOT_STATUSES:
        status = None
    errors = snapshot.get("validation_errors")
    errors = copy.deepcopy(errors) if isinstance(errors, list) else None
    return {"validation_status": status, "validation_errors": errors}


def _snapshot_identity(snapshot):
    return {"snapshot_id": snapshot["snapshot_id"], "sequence": snapshot["sequence"]}


def compare_learned_knowledge_diagnostic_snapshots(earlier, later):
    """Deterministic, read-only comparison of two Prompt 508 diagnostic
    snapshots. `earlier` is the baseline and `later` is the current one,
    exactly in the order given; every numeric delta is
    `later - earlier` (`"direction": "later_minus_earlier"`), never the
    reverse. Returns a new, independent plain dict.

    Invalid input (either snapshot missing, not a dict, or not
    well-formed - see `_snapshot_structural_errors()`) never raises and
    is never repaired or filled in; the result is exactly:

        {
            "valid": False,
            "direction": "later_minus_earlier",
            "errors": ["earlier_snapshot_invalid", "later_snapshot_invalid"],
                                  # only those that apply, in that order
            "invalid_inputs": ["earlier", "later"],      # same, as roles
            "earlier_errors": [<structural error codes; [] if fine>],
            "later_errors": [<same>],
            "earlier_validation_information": <see below>,
            "later_validation_information": <see below>,
        }

    where each `*_validation_information` is `None` (input not a dict)
    or `{"validation_status": <str or None>, "validation_errors":
    <list or None>}` - whatever of the snapshot's own validation data
    was usable.

    Otherwise:

        {
            "valid": True,
            "errors": [],
            "direction": "later_minus_earlier",
            "earlier": {"snapshot_id": ..., "sequence": ...},   # baseline
            "later": {"snapshot_id": ..., "sequence": ...},     # current
            "chronological": <bool>,   # earlier.sequence < later.sequence
                                       # (informational only)
            "comparable": <bool>,      # both snapshots' own
                                       # validation_status is "valid"
            "identical": <bool>,       # no compared field changed
            "changed_fields": [<field>, ...],  # fixed order, see below
            "numeric": {
                "<field>": {"earlier": .., "later": ..,
                            "delta": later - earlier, "changed": <bool>},
                ...
            },     # fields: total_evaluations, accepted_count,
                   # rejected_count, no_candidate_count (int deltas),
                   # acceptance_rate, rejection_rate (float deltas from
                   # the stored rates, unrounded)
            "dominant_rejection_reason": {
                "earlier": .., "later": ..,
                "change": "unchanged" | "changed" | "became_empty"
                          | "became_available" | "not_comparable",
                "changed": <bool or None>,
            },
            "validation_status": {
                "earlier": .., "later": ..,
                "change": "unchanged" | "changed",
                "changed": <bool>,
            },
        }

    `"changed_fields"` lists, in the order numeric fields (as above),
    `dominant_rejection_reason`, `validation_status`, each field that
    changed. A snapshot with `validation_status == "invalid"` holds no
    analysis values (they are `None`, never guessed), so when either
    snapshot is like that `"comparable"` is `False`: each numeric
    entry's `delta` and `changed` are `None` and the dominant reason's
    `change` is `"not_comparable"` (only `validation_status` is
    compared). `"became_empty"` means the reason went from a value to
    `None`; `"became_available"` from `None` to a value. Never mutates
    `earlier` or `later`, never touches any history, statistics, trace,
    or learned record, and is not wired into the gate/decision/response
    path.
    """
    earlier_errors = _snapshot_structural_errors(earlier)
    later_errors = _snapshot_structural_errors(later)
    if earlier_errors or later_errors:
        invalid_inputs = []
        errors = []
        if earlier_errors:
            invalid_inputs.append("earlier")
            errors.append("earlier_snapshot_invalid")
        if later_errors:
            invalid_inputs.append("later")
            errors.append("later_snapshot_invalid")
        return {
            "valid": False,
            "direction": COMPARISON_DIRECTION,
            "errors": errors,
            "invalid_inputs": invalid_inputs,
            "earlier_errors": earlier_errors,
            "later_errors": later_errors,
            "earlier_validation_information": _snapshot_validation_information(earlier),
            "later_validation_information": _snapshot_validation_information(later),
        }

    comparable = (
        earlier["validation_status"] == SNAPSHOT_VALIDATION_VALID
        and later["validation_status"] == SNAPSHOT_VALIDATION_VALID
    )
    changed_fields = []

    numeric = {}
    for field in _SNAPSHOT_NUMERIC_FIELDS:
        before, after = earlier[field], later[field]
        if comparable:
            changed = before != after
            entry = {"earlier": before, "later": after, "delta": after - before, "changed": changed}
            if changed:
                changed_fields.append(field)
        else:
            entry = {"earlier": before, "later": after, "delta": None, "changed": None}
        numeric[field] = entry

    before_reason, after_reason = earlier["dominant_rejection_reason"], later["dominant_rejection_reason"]
    if not comparable:
        reason_change, reason_changed = CHANGE_NOT_COMPARABLE, None
    elif before_reason == after_reason:
        reason_change, reason_changed = CHANGE_UNCHANGED, False
    elif before_reason is None:
        reason_change, reason_changed = CHANGE_BECAME_AVAILABLE, True
    elif after_reason is None:
        reason_change, reason_changed = CHANGE_BECAME_EMPTY, True
    else:
        reason_change, reason_changed = CHANGE_CHANGED, True
    if reason_changed:
        changed_fields.append("dominant_rejection_reason")

    status_changed = earlier["validation_status"] != later["validation_status"]
    if status_changed:
        changed_fields.append("validation_status")

    return {
        "valid": True,
        "errors": [],
        "direction": COMPARISON_DIRECTION,
        "earlier": _snapshot_identity(earlier),
        "later": _snapshot_identity(later),
        "chronological": earlier["sequence"] < later["sequence"],
        "comparable": comparable,
        "identical": not changed_fields,
        "changed_fields": changed_fields,
        "numeric": numeric,
        "dominant_rejection_reason": {
            "earlier": before_reason, "later": after_reason,
            "change": reason_change, "changed": reason_changed,
        },
        "validation_status": {
            "earlier": earlier["validation_status"], "later": later["validation_status"],
            "change": CHANGE_CHANGED if status_changed else CHANGE_UNCHANGED,
            "changed": status_changed,
        },
    }


# ----------------------------------------------------------------------
# Prompt 510 - validation of a Prompt 509 snapshot comparison result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural/consistency check over the
# dict `compare_learned_knowledge_diagnostic_snapshots()` (Prompt 509)
# returns - the same job Prompt 506's validator does for the Prompt 505
# analysis, and it reuses that validator (for the per-snapshot analysis
# values a comparison carries) and the same result shape and error-code
# style rather than adding a parallel framework. Responsibilities stay
# separate: snapshot (508) -> comparison (509) -> comparison validation
# (510). It never regenerates or repairs a comparison, never changes a
# snapshot, and passes no judgement on what a change means (no
# good/bad reading, no score) - it only reports whether the result is
# well-formed and internally consistent.

_COMPARISON_STATES = (
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY,
    CHANGE_BECAME_AVAILABLE, CHANGE_NOT_COMPARABLE,
)
_VALIDATION_STATUS_STATES = (CHANGE_UNCHANGED, CHANGE_CHANGED)
_COMPARISON_VALID_REQUIRED = (
    "valid", "errors", "direction", "earlier", "later", "chronological",
    "comparable", "identical", "changed_fields", "numeric",
    "dominant_rejection_reason", "validation_status",
)
_COMPARISON_INVALID_REQUIRED = (
    "valid", "direction", "errors", "invalid_inputs", "earlier_errors",
    "later_errors", "earlier_validation_information", "later_validation_information",
)
_NUMERIC_ENTRY_FIELDS = ("earlier", "later", "delta", "changed")
_COMPARISON_ROLES = ("earlier", "later")
_NOT_PROVIDED = object()


def _is_finite_number(value):
    return _is_plain_number(value) and math.isfinite(value)


def _is_list_of_str(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_bool(value):
    return isinstance(value, bool)


def _identity_is_well_formed(value):
    return (
        isinstance(value, dict)
        and set(value.keys()) == {"snapshot_id", "sequence"}
        and isinstance(value["snapshot_id"], str) and bool(value["snapshot_id"].strip())
        and _is_plain_int(value["sequence"]) and value["sequence"] >= 1
    )


def _expected_reason_change(comparable, before, after):
    """(change, changed) the Prompt 509 rules imply for two dominant
    reasons - recomputed here independently so it can be checked
    against what the comparison reports."""
    if not comparable:
        return CHANGE_NOT_COMPARABLE, None
    if before == after:
        return CHANGE_UNCHANGED, False
    if before is None:
        return CHANGE_BECAME_AVAILABLE, True
    if after is None:
        return CHANGE_BECAME_EMPTY, True
    return CHANGE_CHANGED, True


def _check_numeric_entry(field, entry, comparable, statuses, errors):
    """Checks one `numeric[field]` entry; returns `(before, after,
    values_ok)` for the cross-checks that follow."""
    is_rate = field in _ANALYSIS_RATE_FIELDS
    before, after = entry["earlier"], entry["later"]
    delta, changed = entry["delta"], entry["changed"]
    values_ok = True

    def check_value(role, value):
        if _is_plain_number(value) and not math.isfinite(value):
            errors.append("non_finite_value:%s.%s" % (field, role))
            return False
        if not _is_finite_number(value) or (not is_rate and not _is_plain_int(value)):
            errors.append("invalid_value_type:%s.%s" % (field, role))
            return False
        return True

    if comparable:
        for role, value in (("earlier", before), ("later", after)):
            values_ok = check_value(role, value) and values_ok
        if not _is_plain_number(delta):
            errors.append("invalid_delta_type:%s" % field)
        elif not math.isfinite(delta):
            errors.append("non_finite_delta:%s" % field)
        elif not is_rate and not _is_plain_int(delta):
            errors.append("invalid_delta_type:%s" % field)
        elif values_ok:
            expected = after - before
            if is_rate:
                correct = math.isclose(delta, expected, rel_tol=_RATE_TOLERANCE,
                                       abs_tol=_RATE_TOLERANCE)
            else:
                correct = delta == expected
            if not correct:
                errors.append("incorrect_delta:%s" % field)
        if not _is_bool(changed):
            errors.append("invalid_changed_flag:%s" % field)
        elif values_ok and changed != (before != after):
            errors.append("inconsistent_changed:%s" % field)
    else:
        if delta is not None:
            errors.append("delta_present_when_not_comparable:%s" % field)
        if changed is not None:
            errors.append("changed_present_when_not_comparable:%s" % field)
        for role, value in (("earlier", before), ("later", after)):
            status = statuses.get(role)
            if status == SNAPSHOT_VALIDATION_INVALID:
                if value is not None:
                    errors.append("value_present_for_invalid_snapshot:%s.%s" % (field, role))
                    values_ok = False
            elif status == SNAPSHOT_VALIDATION_VALID:
                values_ok = check_value(role, value) and values_ok
    return before, after, values_ok


def _validate_valid_comparison(comparison, structural, source_errors):
    for field in _COMPARISON_VALID_REQUIRED:
        if field not in comparison:
            structural.append("missing_field:%s" % field)

    if "errors" in comparison and comparison["errors"] != []:
        structural.append("invalid_errors_for_valid_comparison")
    if "direction" in comparison and comparison["direction"] != COMPARISON_DIRECTION:
        structural.append("invalid_direction")

    identities_ok = True
    for role in _COMPARISON_ROLES:
        if role in comparison and not _identity_is_well_formed(comparison[role]):
            structural.append("invalid_%s_identity" % role)
            identities_ok = False
    if "chronological" in comparison:
        if not _is_bool(comparison["chronological"]):
            structural.append("invalid_chronological")
        elif identities_ok and "earlier" in comparison and "later" in comparison:
            expected = comparison["earlier"]["sequence"] < comparison["later"]["sequence"]
            if comparison["chronological"] != expected:
                structural.append("inconsistent_chronological")

    # --- validation-status comparison ------------------------------------
    statuses = {}
    status_ok = False
    vs = comparison.get("validation_status")
    if "validation_status" in comparison:
        if not (isinstance(vs, dict)
                and set(vs.keys()) == {"earlier", "later", "change", "changed"}):
            structural.append("invalid_validation_status_comparison")
        else:
            status_ok = True
            for role in _COMPARISON_ROLES:
                if vs[role] in _SNAPSHOT_STATUSES:
                    statuses[role] = vs[role]
                else:
                    structural.append("invalid_validation_status_value:%s" % role)
                    status_ok = False
            if vs["change"] not in _VALIDATION_STATUS_STATES:
                structural.append("invalid_validation_status_state")
                status_ok = False
            if not _is_bool(vs["changed"]):
                structural.append("invalid_validation_status_changed_flag")
                status_ok = False
            if status_ok:
                changed = vs["earlier"] != vs["later"]
                if (vs["changed"] != changed
                        or vs["change"] != (CHANGE_CHANGED if changed else CHANGE_UNCHANGED)):
                    structural.append("inconsistent_validation_status_change")
                    status_ok = False

    comparable = None
    if "comparable" in comparison:
        if not _is_bool(comparison["comparable"]):
            structural.append("invalid_comparable")
        else:
            comparable = comparison["comparable"]
            if len(statuses) == 2:
                expected = all(v == SNAPSHOT_VALIDATION_VALID for v in statuses.values())
                if comparable != expected:
                    structural.append("inconsistent_comparable")

    # --- numeric deltas --------------------------------------------------
    numeric = comparison.get("numeric")
    numeric_ok = "numeric" in comparison
    side_values = {"earlier": {}, "later": {}}
    side_ok = {"earlier": True, "later": True}
    changed_numeric = []
    if "numeric" in comparison:
        if not isinstance(numeric, dict):
            structural.append("invalid_numeric")
            numeric_ok = False
        else:
            for field in _SNAPSHOT_NUMERIC_FIELDS:
                if field not in numeric:
                    structural.append("missing_numeric_field:%s" % field)
                    numeric_ok = False
                    continue
                entry = numeric[field]
                if not isinstance(entry, dict):
                    structural.append("invalid_numeric_entry:%s" % field)
                    numeric_ok = False
                    continue
                missing = [k for k in _NUMERIC_ENTRY_FIELDS if k not in entry]
                for key in missing:
                    structural.append("missing_numeric_entry_field:%s.%s" % (field, key))
                if missing:
                    numeric_ok = False
                    continue
                if comparable is None:
                    numeric_ok = False
                    continue
                before, after, values_ok = _check_numeric_entry(
                    field, entry, comparable, statuses, structural)
                if not values_ok:
                    numeric_ok = False
                    side_ok["earlier"] = side_ok["later"] = False
                side_values["earlier"][field] = before
                side_values["later"][field] = after
                if comparable and values_ok and before != after:
                    changed_numeric.append(field)

    # --- dominant rejection reason comparison ------------------------------
    reason_ok = False
    reasons = {}
    reason_changed = False
    d = comparison.get("dominant_rejection_reason")
    if "dominant_rejection_reason" in comparison:
        if not (isinstance(d, dict) and set(d.keys()) == {"earlier", "later", "change", "changed"}):
            structural.append("invalid_dominant_rejection_reason_comparison")
        else:
            reason_ok = True
            for role in _COMPARISON_ROLES:
                if d[role] is not None and d[role] not in _REJECTION_DECISIONS:
                    structural.append("invalid_dominant_rejection_reason_value:%s" % role)
                    reason_ok = False
                else:
                    reasons[role] = d[role]
            if d["change"] not in _COMPARISON_STATES:
                structural.append("invalid_dominant_rejection_reason_state")
                reason_ok = False
            if d["changed"] is not None and not _is_bool(d["changed"]):
                structural.append("invalid_dominant_rejection_reason_changed_flag")
                reason_ok = False
            if reason_ok and comparable is not None:
                for role in _COMPARISON_ROLES:
                    if statuses.get(role) == SNAPSHOT_VALIDATION_INVALID and d[role] is not None:
                        structural.append(
                            "value_present_for_invalid_snapshot:dominant_rejection_reason.%s" % role)
                        reason_ok = False
                expected = _expected_reason_change(comparable, d["earlier"], d["later"])
                if (d["change"], d["changed"]) != expected:
                    structural.append("inconsistent_dominant_rejection_reason_change")
                    reason_ok = False
                else:
                    reason_changed = bool(expected[1])
            else:
                reason_ok = False

    # --- per-snapshot analysis values (reuses the Prompt 506 validator) ------
    for role in _COMPARISON_ROLES:
        if (statuses.get(role) == SNAPSHOT_VALIDATION_VALID and side_ok[role]
                and len(side_values[role]) == len(_SNAPSHOT_NUMERIC_FIELDS)
                and role in reasons):
            analysis = dict(side_values[role])
            analysis["dominant_rejection_reason"] = reasons[role]
            for error in validate_learned_knowledge_statistics_analysis(analysis)["errors"]:
                structural.append("%s_analysis:%s" % (role, error))

    # --- changed_fields / identical --------------------------------------
    changed_fields = comparison.get("changed_fields")
    fields_ok = False
    if "changed_fields" in comparison:
        if not _is_list_of_str(changed_fields):
            structural.append("invalid_changed_fields")
        else:
            fields_ok = True
            if numeric_ok and reason_ok and status_ok and comparable is not None:
                expected = list(changed_numeric)
                if reason_changed:
                    expected.append("dominant_rejection_reason")
                if vs["earlier"] != vs["later"]:
                    expected.append("validation_status")
                if changed_fields != expected:
                    structural.append("inconsistent_changed_fields")
    if "identical" in comparison:
        if not _is_bool(comparison["identical"]):
            structural.append("invalid_identical")
        elif fields_ok and comparison["identical"] != (changed_fields == []):
            structural.append("inconsistent_identical")

    # --- comparison of a source snapshot that is itself not usable ---------
    for role in _COMPARISON_ROLES:
        if statuses.get(role) == SNAPSHOT_VALIDATION_INVALID:
            source_errors.append("source_snapshot_validation_status_invalid:%s" % role)


def _validate_invalid_comparison(comparison, structural, source_errors):
    for field in _COMPARISON_INVALID_REQUIRED:
        if field not in comparison:
            structural.append("missing_field:%s" % field)
    if "direction" in comparison and comparison["direction"] != COMPARISON_DIRECTION:
        structural.append("invalid_direction")

    role_errors = {}
    for role in _COMPARISON_ROLES:
        key = role + "_errors"
        if key in comparison:
            if _is_list_of_str(comparison[key]):
                role_errors[role] = comparison[key]
            else:
                structural.append("invalid_%s" % key)

    invalid_inputs = comparison.get("invalid_inputs")
    if "invalid_inputs" in comparison and not (
            _is_list_of_str(invalid_inputs)
            and all(item in _COMPARISON_ROLES for item in invalid_inputs)):
        structural.append("invalid_invalid_inputs")
    elif len(role_errors) == 2:
        expected_inputs = [role for role in _COMPARISON_ROLES if role_errors[role]]
        if not expected_inputs:
            structural.append("invalid_comparison_without_invalid_input")
        if "invalid_inputs" in comparison and invalid_inputs != expected_inputs:
            structural.append("inconsistent_invalid_inputs")
        if "errors" in comparison and comparison["errors"] != [
                role + "_snapshot_invalid" for role in expected_inputs]:
            structural.append("inconsistent_errors")

    for role in _COMPARISON_ROLES:
        key = role + "_validation_information"
        if key not in comparison or role not in role_errors:
            continue
        info = comparison[key]
        no_dict = any(code in ("snapshot_missing", "snapshot_not_a_dict")
                      for code in role_errors[role])
        if no_dict:
            if info is not None:
                structural.append("inconsistent_%s" % key)
        elif not (
                isinstance(info, dict)
                and set(info.keys()) == {"validation_status", "validation_errors"}
                and (info["validation_status"] is None
                     or info["validation_status"] in _SNAPSHOT_STATUSES)
                and (info["validation_errors"] is None
                     or _is_list_of_str(info["validation_errors"]))):
            structural.append("invalid_%s" % key)

    for role in _COMPARISON_ROLES:
        if role_errors.get(role):
            source_errors.append("source_snapshot_invalid:%s" % role)


def _cross_check_sources(comparison, earlier_snapshot, later_snapshot, structural):
    """Optional check against the actual source snapshots, when the
    caller has them. Reads the snapshots only."""
    for role, snapshot in (("earlier", earlier_snapshot), ("later", later_snapshot)):
        if snapshot is _NOT_PROVIDED:
            continue
        source_problems = _snapshot_structural_errors(snapshot)
        if comparison.get("valid") is False:
            if comparison.get(role + "_errors") != source_problems:
                structural.append("source_errors_mismatch:%s" % role)
            continue
        if source_problems:
            structural.append("comparison_valid_but_source_invalid:%s" % role)
            continue
        if comparison.get(role) != _snapshot_identity(snapshot):
            structural.append("source_mismatch:%s:identity" % role)
        numeric = comparison.get("numeric")
        if isinstance(numeric, dict):
            for field in _SNAPSHOT_NUMERIC_FIELDS:
                entry = numeric.get(field)
                if isinstance(entry, dict) and role in entry and entry[role] != snapshot[field]:
                    structural.append("source_mismatch:%s:%s" % (role, field))
        reason = comparison.get("dominant_rejection_reason")
        if (isinstance(reason, dict) and role in reason
                and reason[role] != snapshot["dominant_rejection_reason"]):
            structural.append("source_mismatch:%s:dominant_rejection_reason" % role)
        status = comparison.get("validation_status")
        if (isinstance(status, dict) and role in status
                and status[role] != snapshot["validation_status"]):
            structural.append("source_mismatch:%s:validation_status" % role)


def validate_learned_knowledge_diagnostic_snapshot_comparison(
        comparison, earlier_snapshot=_NOT_PROVIDED, later_snapshot=_NOT_PROVIDED):
    """Deterministic, read-only validation of `comparison` - the dict
    `compare_learned_knowledge_diagnostic_snapshots()` (Prompt 509) or
    `LearnedKnowledgeDiagnosticSnapshotHistory.compare_latest()` /
    `.compare_sequences()` return. Returns a new, independent dict in
    the same style as Prompt 506's validator:

        {
            "valid": <bool>,        # fully valid comparison
            "well_formed": <bool>,  # the result itself is a faithful,
                                    # internally consistent Prompt 509 result
            "errors": [<str>, ...],
            "warnings": [],         # always a list (empty today)
        }

    `valid` is `True` exactly when `errors` is empty. `well_formed` is
    `False` when the comparison result is malformed or inconsistent
    (those error codes come first, in fixed check order). A comparison
    can be well-formed yet not fully valid, because a source snapshot
    it reports on was not usable: that is reported as
    `"source_snapshot_invalid:<earlier|later>"` (the comparison says a
    snapshot was missing/malformed - the comparison's own
    `valid` is `False`) or
    `"source_snapshot_validation_status_invalid:<earlier|later>"` (the
    snapshot's own `validation_status` is `"invalid"`, so its values
    were never comparable), with `well_formed` still `True`.

    What is checked (valid comparison branch)
    -----------------------------------------
    every field Prompt 509 produces is present with the right type;
    `direction` is `"later_minus_earlier"`; `errors` is empty; both
    snapshot identities are well formed and `chronological` agrees with
    their sequences; `validation_status` and the dominant rejection
    reason use only Prompt 509's state values and agree with the values
    they compare (including the became-available / became-empty /
    changed / unchanged / not-comparable rules); `comparable` agrees
    with the two validation statuses; every numeric field is present
    with `earlier`/`later` values of the right type that are finite,
    a finite numeric `delta` equal to `later - earlier` (exact for
    counts, within Prompt 506's rate tolerance for rates), and a
    `changed` flag that agrees; the values of each valid snapshot pass
    the Prompt 506 analysis validator (errors prefixed
    `"earlier_analysis:"` / `"later_analysis:"`); `changed_fields` and
    `identical` agree with what actually changed; and when a snapshot
    is not comparable, its deltas/flags are `None` and no value is
    invented for a snapshot with `validation_status == "invalid"`.

    What is checked (invalid comparison branch)
    -------------------------------------------
    the fields Prompt 509 produces for invalid input are present;
    `invalid_inputs`, `errors`, and the per-side error/validation-
    information data agree with each other, and at least one input is
    actually reported invalid.

    If `earlier_snapshot` / `later_snapshot` are given (`None` means
    "was missing"), the comparison is also cross-checked against them.

    Never repairs, regenerates, or otherwise changes `comparison` or
    the snapshots; a non-dict `comparison` safely yields
    `"comparison_not_a_dict"`. Not called anywhere in the gate/
    decision/response path; it does not interpret a comparison as good
    or bad. Deterministic: the same inputs always give an equal result.
    """
    structural = []
    source_errors = []

    if not isinstance(comparison, dict):
        structural.append("comparison_not_a_dict")
    elif "valid" not in comparison:
        structural.append("missing_field:valid")
    elif not _is_bool(comparison["valid"]):
        structural.append("invalid_type:valid")
    else:
        if comparison["valid"]:
            _validate_valid_comparison(comparison, structural, source_errors)
        else:
            _validate_invalid_comparison(comparison, structural, source_errors)
        _cross_check_sources(comparison, earlier_snapshot, later_snapshot, structural)

    errors = structural + source_errors
    return {"valid": not errors, "well_formed": not structural, "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 511 - trend summary over multiple validated Prompt 509/510 comparisons
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY function over an ORDERED collection of
# comparison results (the dicts `compare_learned_knowledge_diagnostic_
# snapshots()` (Prompt 509) or `LearnedKnowledgeDiagnosticSnapshotHistory.
# compare_latest()` / `.compare_sequences()` return). It is the next link
# in the existing chain - snapshot (508) -> comparison (509) -> comparison
# validation (510) -> trend summary (511) - and adds no new snapshot,
# comparison, validation, memory, or analytics machinery of its own: every
# comparison handed to it is judged with the *existing*
# `validate_learned_knowledge_diagnostic_snapshot_comparison()` (Prompt
# 510, called here, not reimplemented), and only comparisons that pass
# that validation (`valid` is `True`) contribute to the numeric/
# dominant-rejection-reason trends below. A comparison that does not pass
# is never repaired, guessed at, or silently dropped - it is reported by
# its position in `ineligible_comparisons`, together with the exact
# Prompt 510 errors that disqualified it.
#
# What this is
# ------------
# Purely descriptive: for each of the six Prompt 505 numeric fields, and
# for the dominant rejection reason, this compares the *earliest*
# eligible comparison's "earlier" value against the *latest* eligible
# comparison's "later" value (in the order the caller gave, never
# resorted) and reports one of a small fixed set of states -
# "increased"/"decreased"/"unchanged"/"insufficient_data" for numbers,
# and the existing Prompt 509 `CHANGE_*` states for the rejection reason
# ("unchanged"/"changed"/"became_available"/"became_empty", plus
# "insufficient_data" when there is nothing eligible to compare). No
# score, rank, percentage-of-improvement, or judgement is attached to any
# of these states, and nothing here predicts a future value.
#
# `validation_status` is handled differently on purpose: an *eligible*
# comparison's own two snapshots are always both `"valid"` (that is what
# makes a comparison eligible in the first place - see
# `validate_learned_knowledge_diagnostic_snapshot_comparison()`'s
# `"source_snapshot_validation_status_invalid:<role>"` check, which is
# exactly what makes a comparison touching an `"invalid"` snapshot fail
# Prompt 510 validation), so an eligible-only reading of that field could
# never show anything but `"unchanged"`. What is actually useful to know
# over time is whether the *comparisons themselves* kept passing Prompt
# 510 validation, so this field instead reports whether the very first
# and the very last comparison in the full ordered input (eligible or
# not) were each `"valid"` or `"invalid"` per that existing validator,
# using the same `SNAPSHOT_VALIDATION_VALID`/`SNAPSHOT_VALIDATION_INVALID`
# strings Prompt 508 already defines for that idea. This still never
# repairs an invalid comparison and never changes how eligibility for the
# numeric/rejection-reason trends is decided.
#
# What this is not
# -----------------
# Not a re-evaluation of relevance/reliability, not a second validation
# framework, not a scoring or ranking system, and not wired into the
# gate/decision/response path. Calling this never mutates any comparison
# in `comparisons`; every returned identity/list is an independent copy.
# Deterministic: the same ordered input always yields an equal result.

TREND_INCREASED = "increased"
TREND_DECREASED = "decreased"
TREND_INSUFFICIENT_DATA = "insufficient_data"
# "unchanged" and "changed" (numeric/validation-status trend states) and
# "became_available"/"became_empty" (dominant-rejection-reason trend
# states) reuse the exact Prompt 509 `CHANGE_*` constants rather than
# redeclaring equal-valued ones - a trend's category state is then
# directly comparable to a single comparison's own state.

_TREND_NUMERIC_FIELDS = _SNAPSHOT_NUMERIC_FIELDS  # the same six fields


def _numeric_trend_state(start, end):
    """`"increased"`/`"decreased"`/`CHANGE_UNCHANGED` for two already-
    known numeric values. Never called with a `None` start or end."""
    if end > start:
        return TREND_INCREASED
    if end < start:
        return TREND_DECREASED
    return CHANGE_UNCHANGED


def _numeric_field_trend(field, first_eligible, last_eligible):
    if first_eligible is None:
        return {"state": TREND_INSUFFICIENT_DATA, "start": None, "end": None, "delta": None}
    start = first_eligible["numeric"][field]["earlier"]
    end = last_eligible["numeric"][field]["later"]
    return {"state": _numeric_trend_state(start, end), "start": start, "end": end, "delta": end - start}


def _categorical_trend_state(start, end, allow_appear_disappear):
    """`CHANGE_UNCHANGED`/`CHANGE_CHANGED` (and, when
    `allow_appear_disappear`, `CHANGE_BECAME_AVAILABLE`/
    `CHANGE_BECAME_EMPTY`) for two already-known categorical values.
    `None` here means "no reason"/a legitimate value, not "no data" -
    "no data" is handled by the caller (via `TREND_INSUFFICIENT_DATA`)
    before this is ever reached."""
    if start == end:
        return CHANGE_UNCHANGED
    if allow_appear_disappear:
        if start is None:
            return CHANGE_BECAME_AVAILABLE
        if end is None:
            return CHANGE_BECAME_EMPTY
    return CHANGE_CHANGED


def _dominant_rejection_reason_trend(first_eligible, last_eligible):
    if first_eligible is None:
        return {"state": TREND_INSUFFICIENT_DATA, "start": None, "end": None}
    start = first_eligible["dominant_rejection_reason"]["earlier"]
    end = last_eligible["dominant_rejection_reason"]["later"]
    return {"state": _categorical_trend_state(start, end, True), "start": start, "end": end}


def _validation_status_trend(validations):
    """Whether the very first and very last comparison in the full
    ordered input (eligible or not) each passed Prompt 510 validation -
    see the module-level note above for why this, rather than an
    eligible-only reading of each comparison's own `validation_status`
    field, is what is tracked here. `[]` (no comparisons at all) is the
    only case reported as insufficient data."""
    if not validations:
        return {"state": TREND_INSUFFICIENT_DATA, "start": None, "end": None}
    start = SNAPSHOT_VALIDATION_VALID if validations[0]["valid"] else SNAPSHOT_VALIDATION_INVALID
    end = SNAPSHOT_VALIDATION_VALID if validations[-1]["valid"] else SNAPSHOT_VALIDATION_INVALID
    return {"state": _categorical_trend_state(start, end, False), "start": start, "end": end}


def summarize_learned_knowledge_diagnostic_snapshot_comparison_trend(comparisons):
    """Deterministic, read-only trend summary over `comparisons` - an
    ORDERED collection (oldest first) of comparison dicts, each one
    `compare_learned_knowledge_diagnostic_snapshots()` (Prompt 509) or a
    `LearnedKnowledgeDiagnosticSnapshotHistory` comparison method would
    return. `comparisons=None` or `[]` is treated as an empty history.
    The given order is never changed or re-sorted.

    Every comparison is independently checked with the existing
    `validate_learned_knowledge_diagnostic_snapshot_comparison()`
    (Prompt 510, not reimplemented here); only comparisons whose
    `valid` is `True` are eligible for the numeric and dominant-
    rejection-reason trends. Returns a new, independent plain dict:

        {
            "valid": True,
            "errors": [],
            "direction": "later_minus_earlier",   # same as Prompt 509
            "total_comparisons": <int>,           # len(comparisons)
            "eligible_count": <int>,
            "ineligible_count": <int>,
            "ineligible_comparisons": [
                {"index": <int>, "errors": [<str>, ...]},
                ...
            ],   # in input order; only the ones that failed Prompt 510
                 # validation, each with that validation's own errors
            "chronological_range": {
                "earlier": {"snapshot_id": .., "sequence": ..} or None,
                "later": {"snapshot_id": .., "sequence": ..} or None,
            },   # identity of the earliest eligible comparison's
                 # "earlier" snapshot and the latest eligible
                 # comparison's "later" snapshot; both None when there
                 # is nothing eligible
            "numeric": {
                "<field>": {
                    "state": "increased" | "decreased" | "unchanged"
                             | "insufficient_data",
                    "start": <value or None>,   # earliest eligible's
                                                 # "earlier" value
                    "end": <value or None>,     # latest eligible's
                                                 # "later" value
                    "delta": <end - start, or None>,
                },
                ...
            },   # fields: total_evaluations, accepted_count,
                 # rejected_count, no_candidate_count, acceptance_rate,
                 # rejection_rate
            "dominant_rejection_reason": {
                "state": "unchanged" | "changed" | "became_available"
                         | "became_empty" | "insufficient_data",
                "start": <str or None>, "end": <str or None>,
            },
            "validation_status": {
                "state": "unchanged" | "changed" | "insufficient_data",
                "start": "valid" | "invalid" | None,
                "end": "valid" | "invalid" | None,
            },   # whether the FIRST and LAST comparison in the full
                 # input (eligible or not) each passed Prompt 510
                 # validation - see the module-level note above
        }

    With zero eligible comparisons every `"numeric"` entry and the
    `"dominant_rejection_reason"` entry report `"insufficient_data"`
    with `None` values; `"validation_status"` only does so when
    `comparisons` itself is empty (with at least one comparison, its own
    pass/fail is always knowable, whether or not it is eligible).

    No cause is inferred for any change, no state is described as good
    or bad, nothing is ranked or scored, and no future value is
    predicted. Never repairs, regenerates, or otherwise changes any
    comparison in `comparisons`, never mutates `comparisons` itself, and
    never touches a snapshot, statistics object, trace, or learned
    record. Not called anywhere in the gate/decision/response path.
    Deterministic: the same ordered input always produces an equal
    result.
    """
    comparisons = list(comparisons) if comparisons else []

    validations = []
    eligible = []
    ineligible_comparisons = []
    for index, comparison in enumerate(comparisons):
        validation = validate_learned_knowledge_diagnostic_snapshot_comparison(comparison)
        validations.append(validation)
        if validation["valid"]:
            eligible.append(comparison)
        else:
            ineligible_comparisons.append({"index": index, "errors": list(validation["errors"])})

    first_eligible = eligible[0] if eligible else None
    last_eligible = eligible[-1] if eligible else None

    numeric = {
        field: _numeric_field_trend(field, first_eligible, last_eligible)
        for field in _TREND_NUMERIC_FIELDS
    }
    chronological_range = {
        "earlier": copy.deepcopy(first_eligible["earlier"]) if first_eligible is not None else None,
        "later": copy.deepcopy(last_eligible["later"]) if last_eligible is not None else None,
    }

    return {
        "valid": True,
        "errors": [],
        "direction": COMPARISON_DIRECTION,
        "total_comparisons": len(comparisons),
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible_comparisons),
        "ineligible_comparisons": ineligible_comparisons,
        "chronological_range": chronological_range,
        "numeric": numeric,
        "dominant_rejection_reason": _dominant_rejection_reason_trend(first_eligible, last_eligible),
        "validation_status": _validation_status_trend(validations),
    }


# ----------------------------------------------------------------------
# Prompt 512 - validation of a Prompt 511 trend summary
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY validator over the dict
# `summarize_learned_knowledge_diagnostic_snapshot_comparison_trend()`
# (Prompt 511) returns. It is the next link in the existing chain -
# snapshot (508) -> comparison (509) -> comparison validation (510) ->
# trend summary (511) -> trend summary validation (512) - and follows
# the exact same two-tier shape Prompt 506's and Prompt 510's validators
# already use: `well_formed` (the summary is internally consistent on
# its own terms) and `valid` (also matches its declared source
# comparisons, when they are given). Nothing here regenerates a trend
# summary, repairs one, or changes how Prompt 511 computes one.
#
# What is checked without the source comparisons
# ------------------------------------------------
# every field Prompt 511 produces is present with the right type;
# `direction` is `"later_minus_earlier"`; the top-level `valid`/`errors`
# match what Prompt 511 always produces (`True`/`[]`); `total_comparisons`,
# `eligible_count`, and `ineligible_count` are non-negative integers that
# add up; `ineligible_comparisons` has exactly `ineligible_count` entries,
# each a well-formed `{"index", "errors"}` pair with an in-range index and
# a non-empty list of string errors, with indices strictly increasing (the
# same order Prompt 511 preserves - out-of-order or duplicate indices are
# reported as `"invalid_ineligible_comparison_ordering"` /
# `"duplicate_ineligible_comparison_index"`); `chronological_range` is
# `{"earlier": None, "later": None}` when nothing was eligible and two
# well-formed snapshot identities otherwise; every numeric trend entry
# uses only `"increased"`/`"decreased"`/`"unchanged"`/`"insufficient_data"`
# and, when not `"insufficient_data"`, has finite `start`/`end` of the
# right type, a `delta` equal to `end - start` (exact for counts, within
# Prompt 506's rate tolerance for rates), and a `state` that actually
# matches `start`/`end`; `dominant_rejection_reason` and `validation_status`
# each use only the categorical states legitimate for that field (the
# former also allows `"became_available"`/`"became_empty"` and a `None`
# value; the latter is only ever `"valid"`/`"invalid"`, never `None`
# outside `"insufficient_data"`), consistent with their own `start`/`end`.
# An unrecognized or field-inappropriate state (e.g. `"increased"` on a
# categorical field, or `"became_available"` on `validation_status`) is
# reported as `"unknown_..._trend_state:.."`/`"invalid_trend_value:.."`.
#
# What is additionally checked with the source comparisons
# ----------------------------------------------------------
# If `comparisons` (the same ordered collection the trend summary claims
# to summarize) is given, this recomputes the trend with the existing,
# unmodified `summarize_learned_knowledge_diagnostic_snapshot_comparison_
# trend()` and compares it field by field against `trend_summary`; any
# difference is reported as `"mismatched_field:.."` / `"mismatched_
# numeric:<field>"`. This is the only "generation" that happens here -
# recomputing the correct value in order to compare it, never to replace
# what was given. A trend summary can therefore be well-formed (internally
# consistent) yet not fully valid, when it does not match its declared
# source.
#
# What this is not
# -----------------
# Not a second trend-summary generator, not a repair tool, not a scoring
# or ranking system, and not wired into the gate/decision/response path.
# Never mutates `trend_summary` or `comparisons`. Deterministic: the same
# inputs always give an equal result.

_TREND_REQUIRED_FIELDS = (
    "valid", "errors", "direction", "total_comparisons", "eligible_count",
    "ineligible_count", "ineligible_comparisons", "chronological_range",
    "numeric", "dominant_rejection_reason", "validation_status",
)
_TREND_NUMERIC_ENTRY_FIELDS = ("state", "start", "end", "delta")
_TREND_CATEGORICAL_ENTRY_FIELDS = ("state", "start", "end")
_TREND_INELIGIBLE_ENTRY_FIELDS = ("index", "errors")
_TREND_CHRONOLOGICAL_RANGE_FIELDS = ("earlier", "later")

_NUMERIC_TREND_STATES = (TREND_INCREASED, TREND_DECREASED, CHANGE_UNCHANGED, TREND_INSUFFICIENT_DATA)
_DOMINANT_REASON_TREND_STATES = (
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_AVAILABLE, CHANGE_BECAME_EMPTY,
    TREND_INSUFFICIENT_DATA,
)
_VALIDATION_STATUS_TREND_STATES = (CHANGE_UNCHANGED, CHANGE_CHANGED, TREND_INSUFFICIENT_DATA)


def _is_nonneg_int(value):
    return _is_plain_int(value) and value >= 0


def _check_trend_numeric_entry(field, entry, errors):
    if not (isinstance(entry, dict) and set(entry.keys()) == set(_TREND_NUMERIC_ENTRY_FIELDS)):
        errors.append("invalid_numeric_trend_entry:%s" % field)
        return
    state = entry["state"]
    if state not in _NUMERIC_TREND_STATES:
        errors.append("unknown_numeric_trend_state:%s" % field)
        return
    start, end, delta = entry["start"], entry["end"], entry["delta"]
    if state == TREND_INSUFFICIENT_DATA:
        if start is not None or end is not None or delta is not None:
            errors.append("invalid_insufficient_data_values:numeric.%s" % field)
        return
    is_rate = field in _ANALYSIS_RATE_FIELDS
    values_ok = True
    for role, value in (("start", start), ("end", end)):
        if not _is_finite_number(value) or (not is_rate and not _is_plain_int(value)):
            errors.append("invalid_value_type:numeric.%s.%s" % (field, role))
            values_ok = False
    if not _is_finite_number(delta) or (not is_rate and not _is_plain_int(delta)):
        errors.append("invalid_delta_type:numeric.%s" % field)
        values_ok = False
    if not values_ok:
        return
    expected_delta = end - start
    correct = (math.isclose(delta, expected_delta, rel_tol=_RATE_TOLERANCE, abs_tol=_RATE_TOLERANCE)
               if is_rate else delta == expected_delta)
    if not correct:
        errors.append("incorrect_trend_delta:numeric.%s" % field)
    if state != _numeric_trend_state(start, end):
        errors.append("inconsistent_numeric_trend_state:%s" % field)


def _check_trend_categorical_entry(name, entry, allowed_states, allowed_values,
                                    allow_appear_disappear, none_is_valid_value, errors):
    if not (isinstance(entry, dict) and set(entry.keys()) == set(_TREND_CATEGORICAL_ENTRY_FIELDS)):
        errors.append("invalid_categorical_trend_entry:%s" % name)
        return
    state = entry["state"]
    if state not in allowed_states:
        errors.append("unknown_categorical_trend_state:%s" % name)
        return
    start, end = entry["start"], entry["end"]
    if state == TREND_INSUFFICIENT_DATA:
        if start is not None or end is not None:
            errors.append("invalid_insufficient_data_values:%s" % name)
        return
    for role, value in (("start", start), ("end", end)):
        if value is None:
            if not none_is_valid_value:
                errors.append("invalid_trend_value:%s.%s" % (name, role))
                return
        elif value not in allowed_values:
            errors.append("invalid_trend_value:%s.%s" % (name, role))
            return
    if state != _categorical_trend_state(start, end, allow_appear_disappear):
        errors.append("inconsistent_%s_trend_state" % name)


def _check_ineligible_comparisons(ineligible, total_comparisons, errors):
    """`total_comparisons` may be `None` when it is not known to be a
    valid non-negative int - index bounds are not checked then, but
    every other shape/ordering check still runs."""
    if not isinstance(ineligible, list):
        errors.append("invalid_ineligible_comparisons")
        return
    seen_indices = []
    for entry in ineligible:
        if not (isinstance(entry, dict) and set(entry.keys()) == set(_TREND_INELIGIBLE_ENTRY_FIELDS)):
            errors.append("invalid_ineligible_comparison_entry")
            continue
        index, entry_errors = entry["index"], entry["errors"]
        index_ok = _is_plain_int(index) and (total_comparisons is None or 0 <= index < total_comparisons)
        if not index_ok:
            errors.append("invalid_ineligible_comparison_index")
        else:
            seen_indices.append(index)
        if not (_is_list_of_str(entry_errors) and entry_errors):
            errors.append("invalid_ineligible_comparison_errors")
    if len(set(seen_indices)) != len(seen_indices):
        errors.append("duplicate_ineligible_comparison_index")
    elif seen_indices != sorted(seen_indices):
        errors.append("invalid_ineligible_comparison_ordering")


def _check_trend_chronological_range(range_, eligible_count, errors):
    """`eligible_count` may be `None` when it is not known to be a
    valid non-negative int - only the generic both-None-or-both-
    well-formed shape is checked then."""
    if not (isinstance(range_, dict) and set(range_.keys()) == set(_TREND_CHRONOLOGICAL_RANGE_FIELDS)):
        errors.append("invalid_chronological_range")
        return
    earlier, later = range_["earlier"], range_["later"]
    if eligible_count == 0:
        if earlier is not None or later is not None:
            errors.append("inconsistent_chronological_range")
        return
    if eligible_count is not None:
        for role, value in (("earlier", earlier), ("later", later)):
            if not _identity_is_well_formed(value):
                errors.append("invalid_chronological_range_identity:%s" % role)
    else:
        both_none = earlier is None and later is None
        both_ok = _identity_is_well_formed(earlier) and _identity_is_well_formed(later)
        if not (both_none or both_ok):
            errors.append("invalid_chronological_range")


def validate_learned_knowledge_diagnostic_snapshot_comparison_trend(
        trend_summary, comparisons=_NOT_PROVIDED):
    """Deterministic, read-only validation of `trend_summary` - the dict
    `summarize_learned_knowledge_diagnostic_snapshot_comparison_trend()`
    (Prompt 511) returns. Returns a new, independent dict in the same
    style as the Prompt 506 and Prompt 510 validators:

        {
            "valid": <bool>,        # fully valid trend summary
            "well_formed": <bool>,  # internally consistent on its own
            "errors": [<str>, ...],
            "warnings": [],         # always a list (empty today)
        }

    `valid` is `True` exactly when `errors` is empty. `well_formed` is
    `False` when the summary is malformed or internally inconsistent
    (those error codes come first, in fixed check order) - see the
    module-level note above for exactly what is checked. A summary can
    be well-formed yet not fully valid when `comparisons` (the same
    ordered collection it claims to summarize) is given and does not
    match what recomputing the trend from it actually produces
    (`"mismatched_field:.."` / `"mismatched_numeric:<field>"`).

    Never repairs, regenerates for any purpose other than that one
    optional comparison, or otherwise changes `trend_summary` or
    `comparisons`; a non-dict `trend_summary` safely yields
    `"trend_summary_not_a_dict"`. Not called anywhere in the gate/
    decision/response path; it does not interpret a trend as good or
    bad, rank it, or predict anything from it. Deterministic: the same
    inputs always give an equal result.
    """
    structural = []
    source_errors = []

    if not isinstance(trend_summary, dict):
        structural.append("trend_summary_not_a_dict")
        errors = structural + source_errors
        return {"valid": not errors, "well_formed": not structural, "errors": errors, "warnings": []}

    for field in _TREND_REQUIRED_FIELDS:
        if field not in trend_summary:
            structural.append("missing_field:%s" % field)

    if "valid" in trend_summary and trend_summary["valid"] is not True:
        structural.append("invalid_trend_valid_value")
    if "errors" in trend_summary and trend_summary["errors"] != []:
        structural.append("invalid_trend_errors_value")
    if "direction" in trend_summary and trend_summary["direction"] != COMPARISON_DIRECTION:
        structural.append("invalid_direction")

    counts_ok = True
    for field in ("total_comparisons", "eligible_count", "ineligible_count"):
        if field in trend_summary and not _is_nonneg_int(trend_summary[field]):
            structural.append("invalid_type:%s" % field)
            counts_ok = False

    total_comparisons = trend_summary.get("total_comparisons")
    eligible_count = trend_summary.get("eligible_count")
    ineligible_count = trend_summary.get("ineligible_count")
    all_counts_present = all(
        field in trend_summary for field in ("total_comparisons", "eligible_count", "ineligible_count"))

    if counts_ok and all_counts_present and eligible_count + ineligible_count != total_comparisons:
        structural.append("inconsistent_comparison_counts")

    bound = total_comparisons if _is_nonneg_int(total_comparisons) else None
    if "ineligible_comparisons" in trend_summary:
        ineligible = trend_summary["ineligible_comparisons"]
        if isinstance(ineligible, list):
            if _is_nonneg_int(ineligible_count) and len(ineligible) != ineligible_count:
                structural.append("inconsistent_ineligible_count")
            _check_ineligible_comparisons(ineligible, bound, structural)
        else:
            structural.append("invalid_ineligible_comparisons")

    if "chronological_range" in trend_summary:
        _check_trend_chronological_range(
            trend_summary["chronological_range"],
            eligible_count if _is_nonneg_int(eligible_count) else None,
            structural,
        )

    if "numeric" in trend_summary:
        numeric = trend_summary["numeric"]
        if not isinstance(numeric, dict):
            structural.append("invalid_numeric")
        else:
            for field in _TREND_NUMERIC_FIELDS:
                if field not in numeric:
                    structural.append("missing_numeric_trend_field:%s" % field)
                else:
                    _check_trend_numeric_entry(field, numeric[field], structural)

    if "dominant_rejection_reason" in trend_summary:
        _check_trend_categorical_entry(
            "dominant_rejection_reason", trend_summary["dominant_rejection_reason"],
            _DOMINANT_REASON_TREND_STATES, _REJECTION_DECISIONS, True, True, structural)

    if "validation_status" in trend_summary:
        _check_trend_categorical_entry(
            "validation_status", trend_summary["validation_status"],
            _VALIDATION_STATUS_TREND_STATES, _SNAPSHOT_STATUSES, False, False, structural)

    # --- optional cross-check against the actual source comparisons --------
    if comparisons is not _NOT_PROVIDED:
        expected = summarize_learned_knowledge_diagnostic_snapshot_comparison_trend(comparisons)
        for field in ("total_comparisons", "eligible_count", "ineligible_count",
                      "ineligible_comparisons", "chronological_range",
                      "dominant_rejection_reason", "validation_status"):
            if trend_summary.get(field) != expected[field]:
                source_errors.append("mismatched_field:%s" % field)
        numeric = trend_summary.get("numeric")
        if isinstance(numeric, dict):
            for field in _TREND_NUMERIC_FIELDS:
                if numeric.get(field) != expected["numeric"][field]:
                    source_errors.append("mismatched_numeric:%s" % field)
    errors = structural + source_errors
    return {"valid": not errors, "well_formed": not structural, "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 513 - unified diagnostic report over the existing pipeline
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY aggregation over whatever pieces of
# the existing pipeline the caller already has - some subset of a
# snapshot collection (Prompt 508), an ordered comparison collection
# (Prompt 509, judged by the existing Prompt 510 validator), and a trend
# summary (Prompt 511, judged by the existing Prompt 512 validator).
# Nothing here computes a new metric, re-evaluates a decision, or
# introduces a second snapshot/comparison/trend/validation system: every
# number in the report already exists somewhere in the pipeline, and
# every validation result comes from calling the existing Prompt 510/512
# validators (never reimplemented). The one thing this function computes
# that Prompt 511 does not hand it directly is a trend summary derived
# from `comparisons` when the caller has not already built one - that
# still calls the unmodified Prompt 511 `summarize_...` function rather
# than deriving trend information any other way.
#
# What is in the report
# ----------------------
#   "structural_status" - one of "no_data" / "partial" / "valid" /
#       "invalid" (see `_report_structural_status` below for exactly how
#       it is derived) - purely descriptive: never a score, rank, or
#       recommendation, and never implies a cause or a prediction.
#   "snapshots" - `{"available", "count", "latest"}`: `"latest"` is the
#       most recent snapshot in the given collection, as `record()`
#       produced it - raw values, including that snapshot's own
#       `validation_status`/`validation_errors` (unchanged from Prompt
#       508). `None` when there are no snapshots.
#   "comparison" - `{"available", "total_considered", "latest"}`:
#       `"latest"` is the last (most recent) entry of the given ordered
#       `comparisons` collection - a derived Prompt 509 value, not
#       recomputed here. `None` when `comparisons` is empty.
#   "comparison_validation" - `{"available", "result"}`: `"result"` is
#       exactly what `validate_learned_knowledge_diagnostic_snapshot_
#       comparison()` (Prompt 510) returns for that latest comparison.
#       `None` when there is no latest comparison to validate.
#   "trend" - `{"available", "source", "summary"}`: `"summary"` is
#       either the `trend_summary` the caller passed in directly
#       (`"source": "provided"`) or, when the caller did not have one
#       yet but did pass `comparisons`, the result of calling the
#       existing, unmodified `summarize_learned_knowledge_diagnostic_
#       snapshot_comparison_trend()` on it (`"source": "derived"`).
#       `None` (with `"source": None`) when neither was available.
#   "trend_validation" - `{"available", "result"}`: `"result"` is
#       exactly what `validate_learned_knowledge_diagnostic_snapshot_
#       comparison_trend()` (Prompt 512) returns for that trend summary,
#       cross-checked against `comparisons` when those were given too.
#       `None` when there is no trend summary to validate.
#
# Prompt 522 - optional filtered diagnostic trend sections
# ---------------------------------------------------------
# The same builder can also carry the filtered diagnostic trend of
# Prompts 520-521 (a trend summary over Prompt 518 filtered-snapshot
# comparisons, judged by the Prompt 521 validator). This is strictly
# opt-in: only when the caller passes `filtered_comparisons` and/or
# `filtered_trend_summary` (even as an explicit `None`, meaning "asked
# for, but nothing available") does the report gain three more fields,
# in this order after `"trend_validation"`. A report built without them
# is exactly the Prompt 513 report, field for field.
#   "filtered_trend" - `{"available", "source", "summary"}`, the same
#       three fields `"trend"` has: `"summary"` is the Prompt 520 dict,
#       either passed in (`"source": "provided"`) or, when only
#       `filtered_comparisons` was given, produced by calling the
#       existing, unmodified Prompt 520 summarizer on them
#       (`"source": "derived"`). It is embedded whole and unchanged - its
#       source/valid/invalid comparison counts, numeric and categorical
#       trends, section availability, chronology, ineligible-comparison
#       errors and `"unavailable"` states are read from there, never
#       copied a second time or recomputed. `None` (with
#       `"source": None`) when neither was available.
#   "filtered_trend_validation" - `{"available", "result"}`: exactly what
#       the existing Prompt 521 validator returns for that summary
#       (cross-checked against `filtered_comparisons` when those were
#       given too); `None` when there is no summary to validate.
#   "section_origins" - a fixed map from every report section to what kind
#       of information it holds: `"source"` (a Prompt 508 snapshot as
#       recorded), `"derived_from_snapshots"` (a Prompt 509 comparison),
#       `"derived_from_comparisons"` (a Prompt 511 trend),
#       `"derived_from_filtered_comparisons"` (a Prompt 520 trend) or
#       `"validation"` (a Prompt 510/512/521 result). Availability is the
#       section's own `"available"` flag; an unavailable section holds
#       `None`, never a stand-in value.
# The filtered trend has its own snapshot lineage (Prompt 517 snapshots
# have their own sequences), so it is never cross-checked against the
# `"snapshots"` section. An invalid filtered trend summary makes
# `structural_status` `"invalid"`, exactly as an invalid Prompt 511 trend
# does; comparisons that are merely ineligible inside a valid summary stay
# listed there, with their Prompt 519 errors, and are not repaired.
#
# What this is not
# -----------------
# Not a health/quality score, not a ranking of periods, not a
# recommendation engine, and not wired into the gate/decision/response
# path. Never repairs an invalid comparison or trend summary, never
# fabricates a value for a missing component (a missing piece is
# `"available": False` with `None` alongside it, nothing more), and
# never mutates `snapshots`, `comparisons`, or `trend_summary`. Every
# embedded dict is an independent copy. Deterministic: the same inputs
# always produce an equal result.

REPORT_STATUS_NO_DATA = "no_data"
REPORT_STATUS_PARTIAL = "partial"
REPORT_STATUS_VALID = "valid"
REPORT_STATUS_INVALID = "invalid"

TREND_SOURCE_PROVIDED = "provided"
TREND_SOURCE_DERIVED = "derived"


def _report_snapshots_section(snapshots):
    if isinstance(snapshots, LearnedKnowledgeDiagnosticSnapshotHistory):
        snapshots = snapshots.get_all()
    elif isinstance(snapshots, list):
        snapshots = copy.deepcopy(snapshots)
    else:
        snapshots = []
    latest = snapshots[-1] if snapshots else None
    return {"available": latest is not None, "count": len(snapshots), "latest": latest}


def _report_comparison_sections(comparisons):
    comparisons = list(comparisons) if comparisons else []
    latest = copy.deepcopy(comparisons[-1]) if comparisons else None
    comparison_section = {
        "available": latest is not None,
        "total_considered": len(comparisons),
        "latest": latest,
    }
    validation_result = (
        validate_learned_knowledge_diagnostic_snapshot_comparison(latest) if latest is not None else None)
    comparison_validation_section = {
        "available": validation_result is not None,
        "result": validation_result,
    }
    return comparison_section, comparison_validation_section


def _report_trend_sections(comparisons, trend_summary):
    comparisons = list(comparisons) if comparisons else []
    if trend_summary is not None:
        source = TREND_SOURCE_PROVIDED
        summary = copy.deepcopy(trend_summary)
    elif comparisons:
        source = TREND_SOURCE_DERIVED
        summary = summarize_learned_knowledge_diagnostic_snapshot_comparison_trend(comparisons)
    else:
        source = None
        summary = None

    trend_section = {"available": summary is not None, "source": source, "summary": summary}
    if summary is None:
        validation_result = None
    elif comparisons:
        validation_result = validate_learned_knowledge_diagnostic_snapshot_comparison_trend(
            summary, comparisons=comparisons)
    else:
        validation_result = validate_learned_knowledge_diagnostic_snapshot_comparison_trend(summary)
    trend_validation_section = {"available": validation_result is not None, "result": validation_result}
    return trend_section, trend_validation_section


# What kind of information each report section holds (Prompt 522). Fixed
# text - nothing is computed to produce it.
REPORT_ORIGIN_SOURCE = "source"
REPORT_ORIGIN_DERIVED_FROM_SNAPSHOTS = "derived_from_snapshots"
REPORT_ORIGIN_DERIVED_FROM_COMPARISONS = "derived_from_comparisons"
REPORT_ORIGIN_DERIVED_FROM_FILTERED_COMPARISONS = "derived_from_filtered_comparisons"
REPORT_ORIGIN_VALIDATION = "validation"

_REPORT_SECTION_ORIGINS = {
    "snapshots": REPORT_ORIGIN_SOURCE,
    "comparison": REPORT_ORIGIN_DERIVED_FROM_SNAPSHOTS,
    "comparison_validation": REPORT_ORIGIN_VALIDATION,
    "trend": REPORT_ORIGIN_DERIVED_FROM_COMPARISONS,
    "trend_validation": REPORT_ORIGIN_VALIDATION,
    "filtered_trend": REPORT_ORIGIN_DERIVED_FROM_FILTERED_COMPARISONS,
    "filtered_trend_validation": REPORT_ORIGIN_VALIDATION,
}


def _report_filtered_trend_sections(filtered_comparisons, filtered_trend_summary):
    """The Prompt 522 `"filtered_trend"` / `"filtered_trend_validation"`
    sections, built the way `_report_trend_sections()` builds the Prompt
    511/512 pair: the summary is the caller's own (`"provided"`) or the
    unmodified Prompt 520 summarizer's over `filtered_comparisons`
    (`"derived"`); the validation is the unmodified Prompt 521
    validator's. `_NOT_PROVIDED` and `None` both mean "not given".
    """
    if filtered_comparisons is _NOT_PROVIDED:
        filtered_comparisons = None
    if filtered_trend_summary is _NOT_PROVIDED:
        filtered_trend_summary = None
    if filtered_trend_summary is not None:
        source = TREND_SOURCE_PROVIDED
        summary = copy.deepcopy(filtered_trend_summary)
    elif filtered_comparisons:
        source = TREND_SOURCE_DERIVED
        summary = summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend(
            filtered_comparisons)
    else:
        source = None
        summary = None

    trend_section = {"available": summary is not None, "source": source, "summary": summary}
    if summary is None:
        validation_result = None
    elif filtered_comparisons:
        validation_result = validate_learned_knowledge_filtered_summary_snapshot_comparison_trend(
            summary, comparisons=filtered_comparisons)
    else:
        validation_result = validate_learned_knowledge_filtered_summary_snapshot_comparison_trend(summary)
    validation_section = {"available": validation_result is not None, "result": validation_result}
    return trend_section, validation_section


def _report_structural_status(snapshots_section, comparison_validation_section, trend_validation_section,
                               comparison_section, trend_section,
                               filtered_trend_section=None, filtered_trend_validation_section=None):
    snapshot_invalid = (
        snapshots_section["available"]
        and snapshots_section["latest"].get("validation_status") == SNAPSHOT_VALIDATION_INVALID
    )
    comparison_invalid = (
        comparison_validation_section["available"]
        and comparison_validation_section["result"]["valid"] is False
    )
    trend_invalid = (
        trend_validation_section["available"]
        and trend_validation_section["result"]["valid"] is False
    )
    # Prompt 522: the optional filtered trend. Both arguments are `None`
    # for a report without it, which leaves this derivation exactly as
    # Prompt 513 had it.
    filtered_invalid = (
        filtered_trend_validation_section is not None
        and filtered_trend_validation_section["available"]
        and filtered_trend_validation_section["result"]["valid"] is False
    )
    if snapshot_invalid or comparison_invalid or trend_invalid or filtered_invalid:
        return REPORT_STATUS_INVALID

    all_available = (
        snapshots_section["available"] and comparison_section["available"] and trend_section["available"])
    none_available = (
        not snapshots_section["available"]
        and not comparison_section["available"]
        and not trend_section["available"]
        and not (filtered_trend_section is not None and filtered_trend_section["available"])
    )
    if none_available:
        return REPORT_STATUS_NO_DATA
    if not all_available:
        return REPORT_STATUS_PARTIAL
    return REPORT_STATUS_VALID


def build_learned_knowledge_diagnostic_report(
        snapshots=None, comparisons=None, trend_summary=None,
        filtered_comparisons=_NOT_PROVIDED, filtered_trend_summary=_NOT_PROVIDED):
    """Deterministic, read-only unified diagnostic report combining
    whatever of the existing pipeline the caller has:

    `snapshots` - `None`, a `LearnedKnowledgeDiagnosticSnapshotHistory`
        (its `.get_all()` is used), or a plain oldest-first list of
        Prompt 508 snapshot dicts.
    `comparisons` - `None` or an oldest-first list of Prompt 509
        comparison dicts (the same shape `summarize_learned_knowledge_
        diagnostic_snapshot_comparison_trend()` takes).
    `trend_summary` - `None`, or a Prompt 511 trend summary dict. When
        `None` and `comparisons` is non-empty, one is derived by calling
        the existing, unmodified Prompt 511 summarizer on `comparisons`.
    `filtered_comparisons` / `filtered_trend_summary` - Prompt 522, both
        optional and left out by default: an ordered list of Prompt 518
        filtered-snapshot comparisons and/or a Prompt 520 filtered trend
        summary. Passing either (even `None`) adds the `"filtered_trend"`,
        `"filtered_trend_validation"` and `"section_origins"` fields
        described in the module note above; passing neither leaves the
        report exactly as Prompt 513 built it.

    Returns a new, independent plain dict:

        {
            "valid": True,
            "errors": [],
            "structural_status": "no_data" | "partial" | "valid" | "invalid",
            "snapshots": {"available": <bool>, "count": <int>, "latest": <dict or None>},
            "comparison": {"available": <bool>, "total_considered": <int>, "latest": <dict or None>},
            "comparison_validation": {"available": <bool>, "result": <dict or None>},
            "trend": {"available": <bool>, "source": "provided"|"derived"|None, "summary": <dict or None>},
            "trend_validation": {"available": <bool>, "result": <dict or None>},
        }

    `structural_status` is derived, in order: `"invalid"` when the
    latest snapshot's own `validation_status` is `"invalid"`, or the
    latest comparison fails Prompt 510 validation, or the trend summary
    fails Prompt 512 validation; else `"no_data"` when none of
    snapshots/comparison/trend is available; else `"partial"` when only
    some are; else `"valid"`. It is purely descriptive - never a score,
    health rating, ranking, or recommendation, and it never implies a
    cause for a change or predicts a future one.

    Nothing is fabricated: a component that was not given (or could not
    be derived) is `"available": False` with `None` alongside it, never
    a guessed or default value. Never repairs an invalid comparison or
    trend summary, never mutates `snapshots`, `comparisons`, or
    `trend_summary`; every embedded dict is an independent copy. Not
    called anywhere in the gate/decision/response path; produces no
    UI, chart, score, or recommendation. Deterministic: the same inputs
    always give an equal result.
    """
    snapshots_section = _report_snapshots_section(snapshots)
    comparison_section, comparison_validation_section = _report_comparison_sections(comparisons)
    trend_section, trend_validation_section = _report_trend_sections(comparisons, trend_summary)
    include_filtered = (
        filtered_comparisons is not _NOT_PROVIDED or filtered_trend_summary is not _NOT_PROVIDED)
    if include_filtered:
        filtered_trend_section, filtered_trend_validation_section = _report_filtered_trend_sections(
            filtered_comparisons, filtered_trend_summary)
    else:
        filtered_trend_section = filtered_trend_validation_section = None
    structural_status = _report_structural_status(
        snapshots_section, comparison_validation_section, trend_validation_section,
        comparison_section, trend_section,
        filtered_trend_section, filtered_trend_validation_section)

    report = {
        "valid": True,
        "errors": [],
        "structural_status": structural_status,
        "snapshots": snapshots_section,
        "comparison": comparison_section,
        "comparison_validation": comparison_validation_section,
        "trend": trend_section,
        "trend_validation": trend_validation_section,
    }
    if include_filtered:
        report["filtered_trend"] = filtered_trend_section
        report["filtered_trend_validation"] = filtered_trend_validation_section
        report["section_origins"] = dict(_REPORT_SECTION_ORIGINS)
    return report


# ----------------------------------------------------------------------
# Prompt 514 - validation of a Prompt 513 unified diagnostic report
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY validator over the dict
# `build_learned_knowledge_diagnostic_report()` (Prompt 513) returns. It is
# the last link in the existing chain -
#
#   snapshot (508) -> comparison (509) -> comparison validation (510) ->
#   trend summary (511) -> trend validation (512) -> unified report (513)
#   -> unified report validation (514)
#
# and follows the same two-tier result shape Prompt 506, 510 and 512
# already use: `well_formed` (the report is internally consistent on its
# own terms) and `valid` (also agrees with the source snapshots /
# comparisons / trend summary, when the caller hands those in too).
# Nothing here is a second validation framework: every judgement about a
# component is made by calling the existing validator for it -
# `_snapshot_structural_errors()` (Prompt 508/506) for a snapshot,
# `validate_learned_knowledge_diagnostic_snapshot_comparison()` (510) for
# the latest comparison, `validate_learned_knowledge_diagnostic_snapshot_
# comparison_trend()` (512) for the trend summary, and
# `_report_structural_status()` (513) for the overall status. The 513
# builder itself is only ever CALLED (never modified) when sources are
# given, to recompute what a faithful report would contain so it can be
# compared against what the report says - never to replace it.
#
# A report that FAITHFULLY REPORTS an invalid component is not itself
# invalid: Prompt 513 deliberately embeds an invalid comparison's/trend's
# own validation result and sets `structural_status` to `"invalid"`. This
# validator therefore does not flag "the comparison is invalid" - it flags
# only a report that MISSTATES its components (claims valid what its own
# source validation says is invalid, contradicts itself, fabricates a
# value for a missing component, disagrees with the source data, ...).
#
# What is checked without any source (the report alone)
# ------------------------------------------------------
# every top-level field and every section field is present, of the right
# type, and no unexpected field is added; `valid` is `True` and `errors`
# is `[]` (what Prompt 513 always produces); `structural_status` is one of
# the four supported values and equals what Prompt 513's own derivation
# gives for the sections the report carries; `snapshots.count` /
# `comparison.total_considered` are non-negative integers, consistent with
# `available`; the latest snapshot is a well-formed Prompt 508 snapshot
# (including every preserved metric - total evaluations, accepted,
# rejected and no-candidate counts, acceptance and rejection rates,
# dominant rejection reason - via the existing Prompt 506 analysis
# validator); an unavailable component is `available: False` with `None`
# (and `count`/`total_considered` of `0`), never an empty dict, list,
# zero or other fabricated replacement; `comparison_validation` /
# `trend_validation` are available exactly when the component they judge
# is, are internally consistent (`valid` agrees with `errors`), and agree
# with what re-running the existing 510 / 512 validator on the embedded
# comparison / trend summary gives (`"claims_valid_but_source_invalid:
# <component>"` when the report says valid and that validator says not);
# the trend `source` is a supported value and a `"derived"` trend has
# comparisons behind it; the reported latest snapshot, latest comparison,
# and trend agree with one another on the metrics of any snapshot they
# both describe; and chronological information is ordered (a comparison's
# earlier snapshot precedes its later one, a trend's chronological range
# runs forward, and nothing refers to a snapshot later than the latest
# snapshot).
#
# What is additionally checked with sources
# ------------------------------------------
# If `snapshots` / `comparisons` / `trend_summary` (the exact arguments
# the report was built from) are given, each corresponding section is
# compared with what recomputing it gives, field by field
# (`"source_mismatch:<path>"`), and the ordering of the given snapshots /
# comparisons is checked. A report can therefore be well-formed yet not
# fully valid, when it does not match its declared source.
#
# Prompt 522 - the optional filtered trend sections
# --------------------------------------------------
# A report that carries the Prompt 522 fields (`"filtered_trend"`,
# `"filtered_trend_validation"`, `"section_origins"`) is judged by the
# same checks, extended rather than duplicated: all three fields must be
# present together (a report with none of them is a plain Prompt 513
# report and is judged exactly as before); each section has the same
# shape rules as its Prompt 511/512 twin (`available` / `None` pairing,
# supported `source`, no fabricated placeholder); the embedded
# `filtered_trend_validation.result` must agree with re-running the
# existing Prompt 521 validator on the embedded summary
# (`"claims_valid_but_source_invalid:filtered_trend"`, ...); the
# `structural_status` must equal what the extended Prompt 513 derivation
# gives; `section_origins` must state exactly the fixed origin of every
# section (`"misstated_origin:<section>"` - e.g. derived data presented
# as raw source); and a chronological range is checked only when the
# summary itself says its chronology is ordered (a reversed chronology is
# a state Prompt 520 reports, not an error in the report). With
# `filtered_comparisons` / `filtered_trend_summary` given, the filtered
# sections are compared with what recomputing them gives, like the other
# sections. The filtered trend has its own snapshot lineage, so it is
# never compared against the `"snapshots"` section.
#
# Prompt 527 - chronology across snapshots, comparisons and trends
# ------------------------------------------------------------------
# The chronology checks above are completed, reusing the same
# `"invalid_chronological_ordering:<where>"` code family and the same
# helpers (`_report_sequence()`, `_same_identity()`), so that each way the
# three kinds of data can contradict one another in time is reported:
#
# * snapshots - the report holds only the latest snapshot, but a
#   chronologically ordered run of `count` snapshots (positive, strictly
#   increasing sequences) must end at a sequence of at least `count`;
#   `count` greater than the latest sequence is
#   `"invalid_chronological_ordering:snapshots.count"` (e.g. the
#   snapshots were handed over newest-first). With `snapshots` given, the
#   existing check still requires the source list itself to be strictly
#   increasing (`"...:snapshots"`).
# * comparisons - the existing check requires the given comparisons' later
#   snapshots not to go backwards (`"...:comparisons"`); each given valid
#   comparison must also run forward on its own, its earlier snapshot
#   preceding its later one, however far from the end of the list it is
#   (`"...:comparisons.<index>"`, a 0-based position). The latest
#   comparison is held to the same in the report itself
#   (`"...:comparison.latest"`).
# * trend against comparison - a trend takes its range from the first and
#   last eligible comparison (one passing Prompt 510 validation), so when
#   the latest comparison is eligible a trend must not end after its later
#   snapshot (`"...:trend_after_latest_comparison"`), and a trend the
#   report says it derived from those comparisons must end exactly there
#   (`"inconsistent_trend_source:chronological_range"`).
# * filtered trend - besides the existing range check (made only when the
#   summary says its chronology is ordered), each `chronology.reversed`
#   entry must have `previous_index` before `index`, and the entries'
#   `index` values must strictly increase
#   (`"...:filtered_trend.chronology"`). A reversed filtered chronology,
#   or a reversed filtered comparison the Prompt 520 summary already
#   reports as ineligible, remains a reported state, never an error.
#
# Empty and single-item data is safe by construction: a check needs the
# values it compares and is skipped when they are absent, unavailable or
# malformed (those are other checks' errors), so no snapshots, one
# snapshot, no comparisons, one comparison or an empty filtered trend is
# judged exactly as before. Nothing is repaired, reordered or mutated.
#
# Prompt 528 - consistency between comparisons and trend summaries
# ------------------------------------------------------------------
# The trend summaries in a report (Prompt 511, and the filtered Prompt 520
# one) summarize comparisons. Prompt 528 verifies that they still agree
# with those comparisons, using only what the existing pipeline already
# computed - `_numeric_trend_state()` / `_categorical_trend_state()`, the
# unmodified Prompt 510 comparison validator and, when sources are given,
# the unmodified Prompt 511 / 520 summarizers (to compare with, never to
# replace what the report holds). Error codes, `<trend>` being `trend` or
# `filtered_trend`:
#
# * `inconsistent_comparison_count:<trend>.<field>` - `total_comparisons`
#   (or `eligible_count` / `ineligible_count`) does not match the
#   comparisons the trend claims to summarize: the report's
#   `comparison.total_considered` (any trend source - a derived trend keeps
#   its existing `inconsistent_trend_source:total_comparisons`), the
#   latest comparison being eligible while the trend counts none, or, with
#   the source comparisons given, what they produce.
# * `trend_entry_without_comparison:<path>` - a trend entry names a
#   comparison that does not exist (an `ineligible_comparisons` index or a
#   filtered `available_in` index past the comparisons there are).
# * `extra_trend_entry:<path>` - a trend entry the comparisons do not
#   justify (an eligible comparison listed as ineligible, a numeric field
#   that is not one of the six, a filtered index that is ineligible).
# * `missing_trend_entry:<path>` - a comparison the trend does not
#   account for (an ineligible comparison absent from
#   `ineligible_comparisons`, a numeric field or index left out).
# * `inconsistent_numeric_trend_state:<field>` /
#   `inconsistent_categorical_trend_state:<name>` (`<trend>.` before the
#   name for the filtered trend) - a state that contradicts its source:
#   `"insufficient_data"` exactly when nothing is eligible (filtered:
#   nothing eligible implies it), the state the latest comparison's own
#   two values give when the trend spans exactly that comparison, the
#   trend's `validation_status` ending on whether the latest comparison
#   passed Prompt 510, or, with the sources given, the state they produce.
#   A trend value that disagrees with the same snapshot's value in the
#   latest comparison is `"metric_mismatch:trend_start_vs_comparison:<field>"`
#   (the end side is the existing `trend_vs_comparison` check).
#
# A trend the report's own embedded validation result already declares
# invalid is not judged again: the report faithfully carries that problem
# (as it does a malformed payload), so these checks are for a report that
# presents a trend as valid while it contradicts its comparisons.
#
# Every check needs the values it compares and is skipped when they are
# absent, unavailable or malformed, so empty, sparse and zero-evaluation
# data (no comparisons, nothing eligible, all-zero counts) is judged
# exactly as before. Nothing is repaired or mutated and no metric or
# analysis is added.
#
# What this is not
# -----------------
# Not a report generator, not a repair tool, not a scoring/ranking/
# classification of reports, and not wired into the gate/decision/
# response path. It never repairs an invalid report, never mutates the
# report, snapshots, comparisons, trend summary, or any validation result,
# and never infers a cause or predicts anything. Deterministic: the same
# inputs always give an equal result, with errors in a fixed order.

_REPORT_TOP_LEVEL_FIELDS = (
    "valid", "errors", "structural_status", "snapshots", "comparison",
    "comparison_validation", "trend", "trend_validation",
)
_REPORT_SECTION_FIELDS = {
    "snapshots": ("available", "count", "latest"),
    "comparison": ("available", "total_considered", "latest"),
    "comparison_validation": ("available", "result"),
    "trend": ("available", "source", "summary"),
    "trend_validation": ("available", "result"),
}
_REPORT_SECTIONS = tuple(_REPORT_SECTION_FIELDS)
# Prompt 522: present only in a report built with the filtered trend
# (all three together, or none).
_REPORT_FILTERED_SECTION_FIELDS = {
    "filtered_trend": ("available", "source", "summary"),
    "filtered_trend_validation": ("available", "result"),
}
_REPORT_FILTERED_SECTIONS = tuple(_REPORT_FILTERED_SECTION_FIELDS)
_REPORT_FILTERED_TOP_LEVEL_FIELDS = _REPORT_FILTERED_SECTIONS + ("section_origins",)
_REPORT_STATUSES = (
    REPORT_STATUS_NO_DATA, REPORT_STATUS_PARTIAL, REPORT_STATUS_VALID, REPORT_STATUS_INVALID,
)
_TREND_SOURCES = (TREND_SOURCE_PROVIDED, TREND_SOURCE_DERIVED)
_VALIDATION_RESULT_FIELDS = ("valid", "well_formed", "errors", "warnings")
# Error-code prefixes Prompt 512 produces only when a trend summary is
# cross-checked against its source comparisons - a report built with
# comparisons legitimately carries these on top of the structural errors.
_TREND_SOURCE_ERROR_PREFIXES = ("mismatched_field:", "mismatched_numeric:")
_FILTERED_TREND_SOURCE_ERROR_PREFIXES = _TREND_SOURCE_ERROR_PREFIXES + ("mismatched_categorical:",)
_MISSING = object()


def _report_sequence(identity):
    """The integer `sequence` of a snapshot identity dict, else `None`."""
    if isinstance(identity, dict) and _is_plain_int(identity.get("sequence")):
        return identity["sequence"]
    return None


def _same_identity(first, second):
    return (
        isinstance(first, dict) and isinstance(second, dict)
        and _identity_is_well_formed({k: first.get(k) for k in ("snapshot_id", "sequence")})
        and first.get("snapshot_id") == second.get("snapshot_id")
        and first.get("sequence") == second.get("sequence")
    )


def _report_section_shape(report, name, errors):
    """Checks that `report[name]` is a dict with exactly the fields Prompt
    513 produces and a bool `available`. Returns the section, or `None`
    when it is missing or not usable (the reason is already in `errors`)."""
    if name not in report:
        errors.append("missing_field:%s" % name)
        return None
    section = report[name]
    if not isinstance(section, dict):
        errors.append("invalid_type:%s" % name)
        return None
    expected_fields = (
        _REPORT_SECTION_FIELDS[name] if name in _REPORT_SECTION_FIELDS
        else _REPORT_FILTERED_SECTION_FIELDS[name])
    for field in expected_fields:
        if field not in section:
            errors.append("missing_field:%s.%s" % (name, field))
    for field in section:
        if field not in expected_fields:
            errors.append("unexpected_field:%s.%s" % (name, field))
    if "available" in section and not _is_bool(section["available"]):
        errors.append("invalid_type:%s.available" % name)
        return None
    if "available" not in section:
        return None
    return section


def _check_payload_presence(name, field, section, errors, judged_elsewhere=False):
    """Missing components are explicit, not fabricated: an unavailable
    section holds `None`; an available one holds real data. A payload that
    another validator already judges (the latest comparison - Prompt 510,
    the trend summary - Prompt 512) is only checked for presence here: a
    malformed one is faithfully carried by Prompt 513 and shows up through
    that validator's result, not as a second, parallel type check."""
    if field not in section:
        return
    payload = section[field]
    path = "%s.%s" % (name, field)
    if section["available"] is False:
        if payload is not None:
            errors.append("fabricated_value_for_unavailable_component:%s" % path)
    else:
        if payload is None:
            errors.append("missing_data_marked_available:%s" % path)
        elif not judged_elsewhere:
            if not isinstance(payload, dict):
                errors.append("invalid_type:%s" % path)
            elif not payload:
                errors.append("fabricated_placeholder_value:%s" % path)


def _check_count(name, field, section, errors):
    """`count` / `total_considered`: a non-negative int, 0 exactly when
    unavailable."""
    if field not in section:
        return
    value = section[field]
    path = "%s.%s" % (name, field)
    if not _is_plain_int(value):
        errors.append("invalid_type:%s" % path)
    elif value < 0:
        errors.append("negative_value:%s" % path)
    elif section["available"] is False and value != 0:
        errors.append("fabricated_value_for_unavailable_component:%s" % path)
    elif section["available"] is True and value < 1:
        errors.append("inconsistent_count:%s" % path)


def _check_snapshots_section(section, errors):
    _check_count("snapshots", "count", section, errors)
    _check_payload_presence("snapshots", "latest", section, errors)
    latest = section.get("latest")
    if section["available"] is True and isinstance(latest, dict):
        # The latest snapshot is judged by the existing snapshot check,
        # which itself reuses the Prompt 506 analysis validator: every
        # preserved metric (counts, rates, dominant rejection reason) and
        # the snapshot's own validation status are covered here.
        for problem in _snapshot_structural_errors(latest):
            errors.append("snapshots.latest:%s" % problem)


def _check_comparison_section(section, errors):
    _check_count("comparison", "total_considered", section, errors)
    _check_payload_presence("comparison", "latest", section, errors, judged_elsewhere=True)
    latest = section.get("latest")
    if section["available"] is True and isinstance(latest, dict) and latest.get("valid") is True:
        earlier = _report_sequence(latest.get("earlier"))
        later = _report_sequence(latest.get("later"))
        if earlier is not None and later is not None and earlier >= later:
            errors.append("invalid_chronological_ordering:comparison.latest")


def _check_trend_section(section, errors):
    if "source" in section:
        source = section["source"]
        if section["available"] is True:
            if source not in _TREND_SOURCES:
                errors.append("unsupported_value:trend.source")
        elif source is not None:
            errors.append("fabricated_value_for_unavailable_component:trend.source")
    _check_payload_presence("trend", "summary", section, errors, judged_elsewhere=True)
    summary = section.get("summary")
    if section["available"] is True and isinstance(summary, dict):
        range_ = summary.get("chronological_range")
        if isinstance(range_, dict):
            earlier = _report_sequence(range_.get("earlier"))
            later = _report_sequence(range_.get("later"))
            if earlier is not None and later is not None and earlier >= later:
                errors.append("invalid_chronological_ordering:trend.chronological_range")


def _validation_result_shape_errors(name, result, errors):
    """Shape and self-consistency of an embedded 510 / 512 validation
    result. Returns `True` when it is usable for the recompute check."""
    path = "%s.result" % name
    if not isinstance(result, dict):
        return False
    ok = True
    for field in _VALIDATION_RESULT_FIELDS:
        if field not in result:
            errors.append("missing_field:%s.%s" % (path, field))
            ok = False
    for field in result:
        if field not in _VALIDATION_RESULT_FIELDS:
            errors.append("unexpected_field:%s.%s" % (path, field))
    for field in ("valid", "well_formed"):
        if field in result and not _is_bool(result[field]):
            errors.append("invalid_type:%s.%s" % (path, field))
            ok = False
    for field in ("errors", "warnings"):
        if field in result and not _is_list_of_str(result[field]):
            errors.append("invalid_type:%s.%s" % (path, field))
            ok = False
    if not ok:
        return False
    if result["valid"] != (not result["errors"]):
        errors.append("contradictory_validation_state:%s" % path)
    if result["valid"] and not result["well_formed"]:
        errors.append("contradictory_validation_state:%s.well_formed" % path)
    return True


def _check_validation_section(name, component, component_section, payload_field, section,
                              recompute, errors):
    """`comparison_validation` / `trend_validation`: available exactly when
    the component it judges is, and agrees with re-running the existing
    validator on the embedded component."""
    if component_section is not None and "available" in section:
        if section["available"] != component_section["available"]:
            errors.append("inconsistent_availability:%s" % name)
    _check_payload_presence(name, "result", section, errors)
    result = section.get("result")
    if section["available"] is not True or not isinstance(result, dict):
        return
    if not _validation_result_shape_errors(name, result, errors):
        return
    if component_section is None or component_section.get("available") is not True:
        return
    payload = component_section.get(payload_field)
    if payload is None:
        return
    problem = recompute(result, payload)
    if problem is not None:
        errors.append("%s:%s" % (problem, component))


def _comparison_validation_problem(result, latest):
    expected = validate_learned_knowledge_diagnostic_snapshot_comparison(latest)
    if result == expected:
        return None
    if result["valid"] is True and expected["valid"] is False:
        return "claims_valid_but_source_invalid"
    if result["valid"] is False and expected["valid"] is True:
        return "claims_invalid_but_source_valid"
    return "mismatched_validation_result"


def _trend_validation_problem(result, summary):
    # Without the source comparisons only the structural part of a 512
    # result can be recomputed; whatever a report built WITH comparisons
    # adds on top is a cross-check error and may only be one of the two
    # Prompt 512 source-error kinds.
    expected = validate_learned_knowledge_diagnostic_snapshot_comparison_trend(summary)
    return _trend_result_problem(result, expected, _TREND_SOURCE_ERROR_PREFIXES)


def _filtered_trend_validation_problem(result, summary):
    # Prompt 522: the same judgement for a Prompt 521 result, whose
    # cross-check adds one more source-error kind.
    expected = validate_learned_knowledge_filtered_summary_snapshot_comparison_trend(summary)
    return _trend_result_problem(result, expected, _FILTERED_TREND_SOURCE_ERROR_PREFIXES)


def _trend_result_problem(result, expected, source_error_prefixes):
    if result == expected:
        return None
    if result["valid"] is True and expected["valid"] is False:
        return "claims_valid_but_source_invalid"
    structural = expected["errors"]
    extra = result["errors"][len(structural):]
    if (result["errors"][:len(structural)] == structural
            and result["well_formed"] == expected["well_formed"]
            and all(isinstance(item, str) and item.startswith(source_error_prefixes)
                    for item in extra)
            and result["warnings"] == expected["warnings"]):
        return None
    if result["valid"] is False and expected["valid"] is True and not extra:
        return "claims_invalid_but_source_valid"
    return "mismatched_validation_result"


def _check_filtered_chronology_entries(chronology, errors):
    """Prompt 527: every `chronology.reversed` entry of a filtered trend
    names a comparison (`index`) that goes backwards relative to the one
    before it in the trend (`previous_index`), and the entries run in the
    trend's own order - so `previous_index` precedes `index` and the
    entries' `index` values strictly increase. Malformed entries are the
    Prompt 521 validator's to report, not judged here."""
    entries = chronology.get("reversed") if isinstance(chronology, dict) else None
    if not isinstance(entries, list):
        return
    pairs = [
        (entry["index"], entry["previous_index"]) for entry in entries
        if isinstance(entry, dict) and _is_plain_int(entry.get("index"))
        and _is_plain_int(entry.get("previous_index"))
    ]
    indices = [index for index, _ in pairs]
    if (any(previous >= index for index, previous in pairs)
            or any(later <= earlier for earlier, later in zip(indices, indices[1:]))):
        errors.append("invalid_chronological_ordering:filtered_trend.chronology")


def _check_filtered_trend_section(section, errors):
    """Prompt 522: the `"filtered_trend"` twin of `_check_trend_section()`."""
    if "source" in section:
        source = section["source"]
        if section["available"] is True:
            if source not in _TREND_SOURCES:
                errors.append("unsupported_value:filtered_trend.source")
        elif source is not None:
            errors.append("fabricated_value_for_unavailable_component:filtered_trend.source")
    _check_payload_presence("filtered_trend", "summary", section, errors, judged_elsewhere=True)
    summary = section.get("summary")
    if section["available"] is True and isinstance(summary, dict):
        chronology = summary.get("chronology")
        range_ = summary.get("chronological_range")
        # A reversed chronology is reported by Prompt 520 itself, so the
        # range is only held to running forward when the summary says it
        # is ordered.
        if isinstance(chronology, dict) and chronology.get("ordered") is True and isinstance(range_, dict):
            earlier = _report_sequence(range_.get("earlier"))
            later = _report_sequence(range_.get("later"))
            if earlier is not None and later is not None and earlier >= later:
                errors.append("invalid_chronological_ordering:filtered_trend.chronological_range")
        total = summary.get("total_comparisons")
        if section.get("source") == TREND_SOURCE_DERIVED and _is_plain_int(total) and total == 0:
            errors.append("derived_filtered_trend_without_comparisons")
        _check_filtered_chronology_entries(chronology, errors)


def _check_section_origins(origins, errors):
    """Prompt 522: `section_origins` states exactly the fixed origin of
    every section - derived information is never presented as source."""
    if not isinstance(origins, dict):
        errors.append("invalid_type:section_origins")
        return
    for name, expected in _REPORT_SECTION_ORIGINS.items():
        if name not in origins:
            errors.append("missing_field:section_origins.%s" % name)
        elif origins[name] != expected:
            errors.append("misstated_origin:%s" % name)
    for name in sorted((key for key in origins if key not in _REPORT_SECTION_ORIGINS), key=str):
        errors.append("unexpected_field:section_origins.%s" % name)


def _check_cross_section_consistency(comparison, trend, errors):
    if comparison is None or trend is None:
        return
    comparison_available = comparison.get("available") is True
    trend_available = trend.get("available") is True
    if comparison_available and not trend_available:
        errors.append("missing_trend_for_available_comparison")
    if trend_available and trend.get("source") == TREND_SOURCE_DERIVED:
        if not comparison_available:
            errors.append("derived_trend_without_comparisons")
        else:
            summary = trend.get("summary")
            considered = comparison.get("total_considered")
            if (isinstance(summary, dict) and _is_plain_int(considered)
                    and summary.get("total_comparisons") != considered):
                errors.append("inconsistent_trend_source:total_comparisons")


def _check_status_consistency(report, sections, errors, filtered_sections=None):
    """`structural_status` equals what the existing Prompt 513 derivation
    gives for the sections the report itself carries (including the
    Prompt 522 filtered trend when the report has one)."""
    if report.get("structural_status") not in _REPORT_STATUSES:
        return
    if any(sections[name] is None for name in _REPORT_SECTIONS):
        return
    filtered_trend = filtered_validation = None
    if filtered_sections is not None:
        if any(filtered_sections[name] is None for name in _REPORT_FILTERED_SECTIONS):
            return
        filtered_trend = filtered_sections["filtered_trend"]
        filtered_validation = filtered_sections["filtered_trend_validation"]
        if filtered_validation["available"]:
            result = filtered_validation.get("result")
            if not isinstance(result, dict) or "valid" not in result:
                return
    if sections["snapshots"]["available"] and not isinstance(sections["snapshots"].get("latest"), dict):
        return
    for name in ("comparison_validation", "trend_validation"):
        if sections[name]["available"]:
            result = sections[name].get("result")
            if not isinstance(result, dict) or "valid" not in result:
                return
    expected = _report_structural_status(
        sections["snapshots"], sections["comparison_validation"], sections["trend_validation"],
        sections["comparison"], sections["trend"], filtered_trend, filtered_validation)
    if report["structural_status"] != expected:
        errors.append("inconsistent_structural_status")


def _numeric_value_from(container, field, role):
    entry = container.get(field) if isinstance(container, dict) else None
    return entry.get(role, _MISSING) if isinstance(entry, dict) else _MISSING


def _check_metric_agreement(snapshots, comparison, trend, errors):
    """The three sections describe the same diagnostic data: where two of
    them refer to the same snapshot (same id and sequence), every metric
    they both carry for it must agree."""
    latest_snapshot = snapshots.get("latest") if snapshots and snapshots.get("available") is True else None
    latest_comparison = comparison.get("latest") if comparison and comparison.get("available") is True else None
    summary = trend.get("summary") if trend and trend.get("available") is True else None
    if not isinstance(latest_snapshot, dict):
        latest_snapshot = None
    if not (isinstance(latest_comparison, dict) and latest_comparison.get("valid") is True):
        latest_comparison = None
    if not isinstance(summary, dict):
        summary = None
    trend_range = summary.get("chronological_range") if summary is not None else None
    trend_end = trend_range.get("later") if isinstance(trend_range, dict) else None
    comparison_later = latest_comparison.get("later") if latest_comparison is not None else None

    def compare_values(label, left, right, field):
        if left is _MISSING or right is _MISSING:
            return
        if left != right:
            errors.append("metric_mismatch:%s:%s" % (label, field))

    # comparison.latest.later  <->  snapshots.latest
    if latest_snapshot is not None and _same_identity(comparison_later, latest_snapshot):
        numeric = latest_comparison.get("numeric")
        for field in _SNAPSHOT_NUMERIC_FIELDS:
            compare_values("comparison_vs_snapshots", _numeric_value_from(numeric, field, "later"),
                           latest_snapshot.get(field, _MISSING), field)
        reason = latest_comparison.get("dominant_rejection_reason")
        if isinstance(reason, dict):
            compare_values("comparison_vs_snapshots", reason.get("later", _MISSING),
                           latest_snapshot.get("dominant_rejection_reason", _MISSING),
                           "dominant_rejection_reason")
        status = latest_comparison.get("validation_status")
        if isinstance(status, dict):
            compare_values("comparison_vs_snapshots", status.get("later", _MISSING),
                           latest_snapshot.get("validation_status", _MISSING), "validation_status")

    # trend end  <->  snapshots.latest / comparison.latest.later
    if trend_end is not None:
        trend_numeric = summary.get("numeric")
        trend_reason = summary.get("dominant_rejection_reason")
        for label, identity, values in (
                ("trend_vs_snapshots", latest_snapshot, latest_snapshot),
                ("trend_vs_comparison", comparison_later, latest_comparison)):
            if identity is None or not _same_identity(trend_end, identity):
                continue
            for field in _SNAPSHOT_NUMERIC_FIELDS:
                entry = trend_numeric.get(field) if isinstance(trend_numeric, dict) else None
                if not isinstance(entry, dict) or entry.get("state") == TREND_INSUFFICIENT_DATA:
                    continue
                if label == "trend_vs_snapshots":
                    other = values.get(field, _MISSING)
                else:
                    other = _numeric_value_from(values.get("numeric"), field, "later")
                compare_values(label, entry.get("end", _MISSING), other, field)
            if isinstance(trend_reason, dict) and trend_reason.get("state") != TREND_INSUFFICIENT_DATA:
                if label == "trend_vs_snapshots":
                    other = values.get("dominant_rejection_reason", _MISSING)
                else:
                    reason = values.get("dominant_rejection_reason")
                    other = reason.get("later", _MISSING) if isinstance(reason, dict) else _MISSING
                compare_values(label, trend_reason.get("end", _MISSING), other,
                               "dominant_rejection_reason")


def _check_chronology_against_snapshots(snapshots, comparison, trend, errors):
    """Nothing in the report may refer to a snapshot later than the latest
    snapshot the report itself says it has."""
    if not (snapshots and snapshots.get("available") is True
            and isinstance(snapshots.get("latest"), dict)):
        return
    latest = _report_sequence(snapshots["latest"])
    if latest is None:
        return
    # Prompt 527: sequences are positive and strictly increasing, so a
    # chronologically ordered run of `count` snapshots ends at a sequence
    # of at least `count`. A smaller latest sequence means the run was
    # reversed or otherwise out of order.
    count = snapshots.get("count")
    if _is_plain_int(count) and count > latest:
        errors.append("invalid_chronological_ordering:snapshots.count")
    latest_comparison = comparison.get("latest") if comparison and comparison.get("available") is True else None
    if isinstance(latest_comparison, dict) and latest_comparison.get("valid") is True:
        later = _report_sequence(latest_comparison.get("later"))
        if later is not None and later > latest:
            errors.append("invalid_chronological_ordering:comparison_after_latest_snapshot")
    summary = trend.get("summary") if trend and trend.get("available") is True else None
    if isinstance(summary, dict) and isinstance(summary.get("chronological_range"), dict):
        later = _report_sequence(summary["chronological_range"].get("later"))
        if later is not None and later > latest:
            errors.append("invalid_chronological_ordering:trend_after_latest_snapshot")


def _check_trend_chronology_against_comparison(comparison, trend, errors):
    """Prompt 527: the trend runs to the latest comparison, never past it.

    Prompt 511 takes a trend's chronological range from the first and
    last *eligible* comparison (one that passes Prompt 510 validation) of
    the ordered comparisons, so when the report's latest comparison is
    itself eligible it is the last eligible one: a trend must not end
    after that comparison's later snapshot
    (`"invalid_chronological_ordering:trend_after_latest_comparison"`),
    and a trend the report says it derived from those comparisons must
    end exactly there (`"inconsistent_trend_source:chronological_range"`).
    Judged only when both ends are known; nothing is checked for an
    unavailable, ineligible or malformed comparison or trend."""
    latest_comparison = comparison.get("latest") if comparison and comparison.get("available") is True else None
    if not (isinstance(latest_comparison, dict) and latest_comparison.get("valid") is True
            and validate_learned_knowledge_diagnostic_snapshot_comparison(latest_comparison)["valid"]):
        return
    summary = trend.get("summary") if trend and trend.get("available") is True else None
    if not (isinstance(summary, dict) and isinstance(summary.get("chronological_range"), dict)):
        return
    trend_end = summary["chronological_range"].get("later")
    comparison_end = latest_comparison.get("later")
    trend_sequence, comparison_sequence = _report_sequence(trend_end), _report_sequence(comparison_end)
    if trend_sequence is None or comparison_sequence is None:
        return
    if trend_sequence > comparison_sequence:
        errors.append("invalid_chronological_ordering:trend_after_latest_comparison")
    elif trend.get("source") == TREND_SOURCE_DERIVED and not _same_identity(trend_end, comparison_end):
        errors.append("inconsistent_trend_source:chronological_range")


def _add_error(errors, code):
    if code not in errors:
        errors.append(code)


def _report_trend_summary(section):
    """The summary of an available trend section, else `None`."""
    summary = section.get("summary") if isinstance(section, dict) and section.get("available") is True else None
    return summary if isinstance(summary, dict) else None


def _judged_trend_summary(section, validation_section):
    """The summary of an available trend section that the report presents
    as valid - the one Prompt 528 checks against the comparisons. When the
    embedded Prompt 512 / 521 validation result already says the trend is
    invalid, the report faithfully carries that problem (its own
    `structural_status` and result say so) and it is not reported a second
    time, the same way a malformed payload is left to its own validator."""
    summary = _report_trend_summary(section)
    if summary is None:
        return None
    result = validation_section.get("result") if isinstance(validation_section, dict) else None
    if isinstance(result, dict) and result.get("valid") is False:
        return None
    return summary


def _trend_entry_state(entry):
    state = entry.get("state") if isinstance(entry, dict) else None
    return state if isinstance(state, str) else None


def _trend_ineligible_indices(summary):
    """The indices a trend lists as ineligible (sorted), or `None` when the
    list is missing or not a list."""
    entries = summary.get("ineligible_comparisons")
    if not isinstance(entries, list):
        return None
    return sorted({entry["index"] for entry in entries
                   if isinstance(entry, dict) and _is_plain_int(entry.get("index"))})


def _trend_categorical_entries(summary, filtered):
    """`{name: entry}` for a trend's categorical states: the Prompt 511
    `dominant_rejection_reason` (or the Prompt 520 `categorical` sections)
    and the top-level `validation_status`."""
    entries = {}
    if filtered:
        categorical = summary.get("categorical")
        if isinstance(categorical, dict):
            for section in _FILTERED_TREND_CATEGORICAL_SECTIONS:
                if section in categorical:
                    entries[section] = categorical[section]
    else:
        if "dominant_rejection_reason" in summary:
            entries["dominant_rejection_reason"] = summary["dominant_rejection_reason"]
    if "validation_status" in summary:
        entries["validation_status"] = summary["validation_status"]
    return entries


def _check_trend_states_against_eligibility(summary, filtered, errors):
    """A trend with nothing eligible reports `insufficient_data` everywhere
    (and, for the Prompt 511 trend, only then: it always has a state once
    something is eligible); with no comparisons at all its
    `validation_status` is insufficient too."""
    prefix = "filtered_trend." if filtered else ""
    total, eligible = summary.get("total_comparisons"), summary.get("eligible_count")
    numeric = summary.get("numeric")
    if _is_nonneg_int(eligible):
        entries = []
        if isinstance(numeric, dict):
            entries += [("numeric", field, numeric.get(field)) for field in _TREND_NUMERIC_FIELDS]
        entries += [("categorical", name, entry)
                    for name, entry in _trend_categorical_entries(summary, filtered).items()
                    if name != "validation_status"]
        for kind, name, entry in entries:
            state = _trend_entry_state(entry)
            if state is None:
                continue
            insufficient = state == TREND_INSUFFICIENT_DATA
            if (eligible == 0 and not insufficient) or (eligible > 0 and insufficient and not filtered):
                _add_error(errors, "inconsistent_%s_trend_state:%s%s" % (kind, prefix, name))
    if _is_nonneg_int(total):
        state = _trend_entry_state(summary.get("validation_status"))
        if state is not None and (state == TREND_INSUFFICIENT_DATA) != (total == 0):
            _add_error(errors, "inconsistent_categorical_trend_state:%svalidation_status" % prefix)
    # An entry for something that is not one of the trend's fixed fields
    # summarizes no comparison data at all.
    name = "filtered_trend" if filtered else "trend"
    if isinstance(numeric, dict):
        for key in sorted((key for key in numeric if key not in _TREND_NUMERIC_FIELDS), key=str):
            _add_error(errors, "extra_trend_entry:%s.numeric.%s" % (name, key))
    categorical = summary.get("categorical") if filtered else None
    if isinstance(categorical, dict):
        for key in sorted((key for key in categorical if key not in _FILTERED_TREND_CATEGORICAL_SECTIONS), key=str):
            _add_error(errors, "extra_trend_entry:filtered_trend.categorical.%s" % key)


def _check_trend_against_latest_comparison(comparison, trend, errors):
    """The report's trend against the report's own latest comparison and
    its `total_considered`. Judged only when both are available and the
    values compared are present."""
    summary = _report_trend_summary(trend)
    latest = comparison.get("latest") if isinstance(comparison, dict) and comparison.get("available") is True else None
    considered = comparison.get("total_considered") if isinstance(comparison, dict) else None
    if summary is None or not isinstance(latest, dict) or not _is_nonneg_int(considered) or considered < 1:
        return
    derived = trend.get("source") == TREND_SOURCE_DERIVED
    total = summary.get("total_comparisons")
    eligible_latest = validate_learned_knowledge_diagnostic_snapshot_comparison(latest)["valid"] is True
    indices = _trend_ineligible_indices(summary)

    if _is_nonneg_int(total):
        if total != considered:
            # A derived trend's count is the existing
            # `inconsistent_trend_source:total_comparisons` error.
            if not derived:
                _add_error(errors, "inconsistent_comparison_count:trend.total_comparisons")
                for index in indices or ():
                    if index >= considered:
                        _add_error(errors, "trend_entry_without_comparison:trend.ineligible_comparisons.%d" % index)
        else:
            last = considered - 1
            if indices is not None:
                if eligible_latest and last in indices:
                    _add_error(errors, "extra_trend_entry:trend.ineligible_comparisons.%d" % last)
                if not eligible_latest and last not in indices:
                    _add_error(errors, "missing_trend_entry:trend.ineligible_comparisons.%d" % last)
            eligible = summary.get("eligible_count")
            if eligible_latest and _is_nonneg_int(eligible) and eligible == 0:
                _add_error(errors, "inconsistent_comparison_count:trend.eligible_count")
            status = summary.get("validation_status")
            if isinstance(status, dict) and status.get("state") in (CHANGE_UNCHANGED, CHANGE_CHANGED):
                expected = SNAPSHOT_VALIDATION_VALID if eligible_latest else SNAPSHOT_VALIDATION_INVALID
                roles = ("end", "start") if total == 1 else ("end",)
                if any(status.get(role) in _SNAPSHOT_STATUSES and status.get(role) != expected
                       for role in roles):
                    _add_error(errors, "inconsistent_categorical_trend_state:validation_status")

    # The trend against the latest comparison's own two snapshots: where
    # the trend starts / ends at one of them, its value there is that
    # snapshot's value, and where it spans exactly this comparison its
    # state is the one those two values give.
    range_ = summary.get("chronological_range")
    if not (eligible_latest and isinstance(range_, dict)):
        return
    starts_here = _same_identity(range_.get("earlier"), latest.get("earlier"))
    ends_here = _same_identity(range_.get("later"), latest.get("later"))
    if not starts_here:
        return
    numeric = summary.get("numeric")
    if isinstance(numeric, dict):
        for field in _TREND_NUMERIC_FIELDS:
            entry = numeric.get(field)
            if not isinstance(entry, dict) or entry.get("state") == TREND_INSUFFICIENT_DATA:
                continue
            first = _numeric_value_from(latest.get("numeric"), field, "earlier")
            second = _numeric_value_from(latest.get("numeric"), field, "later")
            if not _is_finite_number(first):
                continue
            if _is_finite_number(entry.get("start")) and entry["start"] != first:
                _add_error(errors, "metric_mismatch:trend_start_vs_comparison:%s" % field)
            if (ends_here and _is_finite_number(second) and isinstance(entry.get("state"), str)
                    and entry["state"] != _numeric_trend_state(first, second)):
                _add_error(errors, "inconsistent_numeric_trend_state:%s" % field)
    reason, latest_reason = summary.get("dominant_rejection_reason"), latest.get("dominant_rejection_reason")
    if (isinstance(reason, dict) and isinstance(latest_reason, dict) and "earlier" in latest_reason
            and reason.get("state") != TREND_INSUFFICIENT_DATA):
        if "start" in reason and reason["start"] != latest_reason["earlier"]:
            _add_error(errors, "metric_mismatch:trend_start_vs_comparison:dominant_rejection_reason")
        if (ends_here and "later" in latest_reason and isinstance(reason.get("state"), str)
                and reason["state"] != _categorical_trend_state(
                    latest_reason["earlier"], latest_reason["later"], True)):
            _add_error(errors, "inconsistent_categorical_trend_state:dominant_rejection_reason")


def _check_filtered_trend_indices(summary, errors):
    """Every comparison index a filtered trend names (`available_in`) is a
    comparison it has and one it counts as eligible."""
    total = summary.get("total_comparisons")
    ineligible = _trend_ineligible_indices(summary)
    if not _is_nonneg_int(total) or ineligible is None:
        return
    places = []
    numeric = summary.get("numeric")
    if isinstance(numeric, dict):
        places += [("numeric.%s" % field, numeric.get(field)) for field in _TREND_NUMERIC_FIELDS]
    categorical = summary.get("categorical")
    if isinstance(categorical, dict):
        places += [("categorical.%s" % name, categorical.get(name)) for name in _FILTERED_TREND_CATEGORICAL_SECTIONS]
    availability = summary.get("section_availability")
    if isinstance(availability, dict):
        places += [("section_availability.%s" % name, availability.get(name)) for name in _SUMMARY_SECTIONS]
    for path, entry in places:
        available_in = entry.get("available_in") if isinstance(entry, dict) else None
        if not isinstance(available_in, list):
            continue
        for index in available_in:
            if not _is_plain_int(index):
                continue
            if index < 0 or index >= total:
                _add_error(errors, "trend_entry_without_comparison:filtered_trend.%s.available_in.%d" % (path, index))
            elif index in ineligible:
                _add_error(errors, "extra_trend_entry:filtered_trend.%s.available_in.%d" % (path, index))


def _check_trend_against_source_comparisons(name, summary, expected, comparison_count, filtered, errors):
    """`summary` (the report's trend) against `expected`, what the
    existing summarizer produces for the given source comparisons."""
    if not isinstance(summary, dict) or not isinstance(expected, dict):
        return
    prefix = "filtered_trend." if filtered else ""
    for field in ("total_comparisons", "eligible_count", "ineligible_count"):
        value = summary.get(field)
        if _is_nonneg_int(value) and value != expected.get(field):
            _add_error(errors, "inconsistent_comparison_count:%s.%s" % (name, field))

    reported, wanted = _trend_ineligible_indices(summary), _trend_ineligible_indices(expected)
    if reported is not None and wanted is not None:
        for index in reported:
            if index not in wanted:
                code = ("trend_entry_without_comparison" if index < 0 or index >= comparison_count
                        else "extra_trend_entry")
                _add_error(errors, "%s:%s.ineligible_comparisons.%d" % (code, name, index))
        for index in wanted:
            if index not in reported:
                _add_error(errors, "missing_trend_entry:%s.ineligible_comparisons.%d" % (name, index))

    def compare_entry(path, reported_entry, expected_entry, state_code):
        state, wanted_state = _trend_entry_state(reported_entry), _trend_entry_state(expected_entry)
        if state is not None and wanted_state is not None and state != wanted_state:
            _add_error(errors, state_code)
        if not filtered:
            return
        available_in = reported_entry.get("available_in") if isinstance(reported_entry, dict) else None
        wanted_in = expected_entry.get("available_in") if isinstance(expected_entry, dict) else None
        if not (isinstance(available_in, list) and isinstance(wanted_in, list)
                and all(_is_plain_int(i) for i in available_in + wanted_in)):
            return
        for index in sorted(set(available_in) - set(wanted_in)):
            code = ("trend_entry_without_comparison" if index < 0 or index >= comparison_count
                    else "extra_trend_entry")
            _add_error(errors, "%s:%s.%s.available_in.%d" % (code, name, path, index))
        for index in sorted(set(wanted_in) - set(available_in)):
            _add_error(errors, "missing_trend_entry:%s.%s.available_in.%d" % (name, path, index))

    numeric, wanted_numeric = summary.get("numeric"), expected.get("numeric")
    if isinstance(numeric, dict) and isinstance(wanted_numeric, dict):
        for key in sorted((key for key in numeric if key not in _TREND_NUMERIC_FIELDS), key=str):
            _add_error(errors, "extra_trend_entry:%s.numeric.%s" % (name, key))
        for field in _TREND_NUMERIC_FIELDS:
            if field not in numeric:
                _add_error(errors, "missing_trend_entry:%s.numeric.%s" % (name, field))
            elif field in wanted_numeric:
                compare_entry("numeric.%s" % field, numeric[field], wanted_numeric[field],
                              "inconsistent_numeric_trend_state:%s%s" % (prefix, field))

    categorical = _trend_categorical_entries(summary, filtered)
    wanted_categorical = _trend_categorical_entries(expected, filtered)
    for key in wanted_categorical:
        if key in categorical:
            path = key if key == "validation_status" or not filtered else "categorical.%s" % key
            compare_entry(path, categorical[key], wanted_categorical[key],
                          "inconsistent_categorical_trend_state:%s%s" % (prefix, key))


def _validate_report_structure(report):
    errors = []
    for field in _REPORT_TOP_LEVEL_FIELDS:
        if field not in report and field not in _REPORT_SECTIONS:
            errors.append("missing_field:%s" % field)
    filtered_present = any(field in report for field in _REPORT_FILTERED_TOP_LEVEL_FIELDS)
    for field in report:
        if field not in _REPORT_TOP_LEVEL_FIELDS and field not in _REPORT_FILTERED_TOP_LEVEL_FIELDS:
            errors.append("unexpected_field:%s" % field)
    if filtered_present and "section_origins" not in report:
        errors.append("missing_field:section_origins")

    if "valid" in report:
        if not _is_bool(report["valid"]):
            errors.append("invalid_type:valid")
        elif report["valid"] is not True:
            errors.append("invalid_report_valid_value")
    if "errors" in report:
        if not isinstance(report["errors"], list):
            errors.append("invalid_type:errors")
        elif report["errors"] != []:
            errors.append("invalid_report_errors_value")
    if "structural_status" in report:
        status = report["structural_status"]
        if not isinstance(status, str):
            errors.append("invalid_type:structural_status")
        elif status not in _REPORT_STATUSES:
            errors.append("unsupported_status_value:structural_status")

    sections = {name: _report_section_shape(report, name, errors) for name in _REPORT_SECTIONS}

    if sections["snapshots"] is not None:
        _check_snapshots_section(sections["snapshots"], errors)
    if sections["comparison"] is not None:
        _check_comparison_section(sections["comparison"], errors)
    if sections["trend"] is not None:
        _check_trend_section(sections["trend"], errors)
    if sections["comparison_validation"] is not None:
        _check_validation_section(
            "comparison_validation", "comparison", sections["comparison"], "latest",
            sections["comparison_validation"], _comparison_validation_problem, errors)
    if sections["trend_validation"] is not None:
        _check_validation_section(
            "trend_validation", "trend", sections["trend"], "summary",
            sections["trend_validation"], _trend_validation_problem, errors)

    filtered_sections = None
    if filtered_present:
        filtered_sections = {
            name: _report_section_shape(report, name, errors) for name in _REPORT_FILTERED_SECTIONS}
        if filtered_sections["filtered_trend"] is not None:
            _check_filtered_trend_section(filtered_sections["filtered_trend"], errors)
        if filtered_sections["filtered_trend_validation"] is not None:
            _check_validation_section(
                "filtered_trend_validation", "filtered_trend", filtered_sections["filtered_trend"],
                "summary", filtered_sections["filtered_trend_validation"],
                _filtered_trend_validation_problem, errors)
        if "section_origins" in report:
            _check_section_origins(report["section_origins"], errors)

    _check_cross_section_consistency(sections["comparison"], sections["trend"], errors)
    _check_metric_agreement(sections["snapshots"], sections["comparison"], sections["trend"], errors)
    _check_chronology_against_snapshots(
        sections["snapshots"], sections["comparison"], sections["trend"], errors)
    _check_trend_chronology_against_comparison(sections["comparison"], sections["trend"], errors)
    # Prompt 528: trend summaries against their comparisons.
    trend_summary = _judged_trend_summary(sections["trend"], sections["trend_validation"])
    if trend_summary is not None:
        _check_trend_states_against_eligibility(trend_summary, False, errors)
        _check_trend_against_latest_comparison(sections["comparison"], sections["trend"], errors)
    if filtered_sections is not None:
        filtered_summary = _judged_trend_summary(
            filtered_sections["filtered_trend"], filtered_sections["filtered_trend_validation"])
        if filtered_summary is not None:
            _check_trend_states_against_eligibility(filtered_summary, True, errors)
            _check_filtered_trend_indices(filtered_summary, errors)
    _check_status_consistency(report, sections, errors, filtered_sections)
    return errors


def _source_snapshot_list(snapshots):
    if isinstance(snapshots, LearnedKnowledgeDiagnosticSnapshotHistory):
        return snapshots.get_all()
    return snapshots if isinstance(snapshots, list) else []


def _ordered_keys(actual, expected):
    extra = sorted((key for key in actual if key not in expected), key=str)
    return list(expected) + extra


def _diff_into(path, actual, expected, errors, depth=0, ignore=()):
    """Appends `"source_mismatch:<path>"` for each place `actual` differs
    from `expected`, one level of detail below each section's payload
    (`snapshots.latest.total_evaluations`, `trend.summary.numeric`, ...)."""
    if actual == expected:
        return
    if depth < 2 and isinstance(actual, dict) and isinstance(expected, dict):
        for key in _ordered_keys(actual, expected):
            if key in ignore:
                continue
            if key not in actual or key not in expected or actual[key] != expected[key]:
                _diff_into("%s.%s" % (path, key), actual.get(key), expected.get(key),
                           errors, depth + 1)
        return
    errors.append("source_mismatch:%s" % path)


# Prompt 529 - each comparison against the source snapshots it names.
# The codes the existing Prompt 510 validator's own source cross-check
# (`_cross_check_sources()`) produces; a comparison's other problems are
# reported elsewhere (trend eligibility, the embedded validation result).
_COMPARISON_SOURCE_CODE_PREFIXES = (
    "comparison_valid_but_source_invalid:", "source_mismatch:", "source_errors_mismatch:",
)


def _find_source_snapshot(snapshot_list, identity):
    """The snapshot in `snapshot_list` with `identity`'s id and sequence,
    or `None` when the identity is unusable or names none of them (a
    missing snapshot is a missing state, never guessed at)."""
    if not isinstance(identity, dict):
        return None
    for snapshot in snapshot_list:
        if _same_identity(identity, snapshot):
            return snapshot
    return None


def _comparison_source_problems(comparison, snapshot_list):
    """Codes for how `comparison` contradicts the source snapshots it
    names, found by running the existing Prompt 510 validator WITH those
    snapshots. Empty when the comparison is not a valid-marked dict, when
    either snapshot is not among `snapshot_list`, or when nothing
    contradicts. Reads only."""
    if not isinstance(comparison, dict) or comparison.get("valid") is not True:
        return []
    earlier = _find_source_snapshot(snapshot_list, comparison.get("earlier"))
    later = _find_source_snapshot(snapshot_list, comparison.get("later"))
    if earlier is None or later is None:
        return []
    result = validate_learned_knowledge_diagnostic_snapshot_comparison(comparison, earlier, later)
    return [code for code in result["errors"]
            if isinstance(code, str) and code.startswith(_COMPARISON_SOURCE_CODE_PREFIXES)]


def _check_comparisons_against_snapshots(report, snapshot_list, listed, errors):
    """Prompt 529: every given comparison that says it is valid must agree
    with the snapshots it names (so an invalid or different source
    snapshot can never sit behind a valid comparison), and the report's
    embedded comparison validation may not call the latest one valid when
    it does not."""
    latest_problems = []
    for index, item in enumerate(listed):
        problems = _comparison_source_problems(item, snapshot_list)
        for code in problems:
            errors.append("comparison_source_inconsistent:%d:%s" % (index, code))
        if index == len(listed) - 1:
            latest_problems = problems
    section = report.get("comparison_validation")
    result = section.get("result") if isinstance(section, dict) else None
    if (latest_problems and isinstance(result, dict) and result.get("valid") is True
            and isinstance(section.get("available"), bool) and section["available"]):
        errors.append("claims_valid_but_source_invalid:comparison_sources")


def _check_report_against_sources(report, snapshots, comparisons, trend_summary,
                                  filtered_comparisons=_NOT_PROVIDED, filtered_trend_summary=_NOT_PROVIDED):
    """Errors for how the report differs from what the given sources
    produce, plus the ordering of the sources themselves. Sources the
    caller did not give are not checked."""
    errors = []
    snapshots_given = snapshots is not _NOT_PROVIDED
    comparisons_given = comparisons is not _NOT_PROVIDED
    trend_given = trend_summary is not _NOT_PROVIDED and trend_summary is not None

    if snapshots_given and snapshots is not None and not isinstance(
            snapshots, (LearnedKnowledgeDiagnosticSnapshotHistory, list)):
        errors.append("invalid_source:snapshots")
        snapshots_given = False
    if comparisons_given and comparisons is not None and not isinstance(comparisons, (list, tuple)):
        errors.append("invalid_source:comparisons")
        comparisons_given = False

    expected = build_learned_knowledge_diagnostic_report(
        snapshots=snapshots if snapshots_given else None,
        comparisons=comparisons if comparisons_given else None,
        trend_summary=trend_summary if trend_summary is not _NOT_PROVIDED else None,
    )

    if snapshots_given:
        ordered = [_report_sequence(item) for item in _source_snapshot_list(snapshots)]
        ordered = [value for value in ordered if value is not None]
        if any(later <= earlier for earlier, later in zip(ordered, ordered[1:])):
            errors.append("invalid_chronological_ordering:snapshots")
        source_latest = expected["snapshots"]["latest"]
        reported = report.get("snapshots")
        if (isinstance(reported, dict) and isinstance(reported.get("latest"), dict)
                and isinstance(source_latest, dict)
                and source_latest.get("validation_status") == SNAPSHOT_VALIDATION_INVALID
                and reported["latest"].get("validation_status") == SNAPSHOT_VALIDATION_VALID):
            errors.append("claims_valid_but_source_invalid:snapshot")
        _diff_into("snapshots", report.get("snapshots"), expected["snapshots"], errors)

    if comparisons_given:
        listed = list(comparisons) if comparisons else []
        later_sequences = [
            _report_sequence(item.get("later")) for item in listed
            if isinstance(item, dict) and item.get("valid") is True
        ]
        later_sequences = [value for value in later_sequences if value is not None]
        if any(later < earlier for earlier, later in zip(later_sequences, later_sequences[1:])):
            errors.append("invalid_chronological_ordering:comparisons")
        # Prompt 527: each comparison must itself run forward - its
        # earlier snapshot precedes its later one - not only the latest.
        for index, item in enumerate(listed):
            if isinstance(item, dict) and item.get("valid") is True:
                earlier = _report_sequence(item.get("earlier"))
                later = _report_sequence(item.get("later"))
                if earlier is not None and later is not None and earlier >= later:
                    errors.append("invalid_chronological_ordering:comparisons.%d" % index)
        _diff_into("comparison", report.get("comparison"), expected["comparison"], errors)
        _diff_into("comparison_validation", report.get("comparison_validation"),
                   expected["comparison_validation"], errors)
        # Prompt 529: the comparisons against the snapshots they name.
        if snapshots_given and snapshots is not None:
            _check_comparisons_against_snapshots(
                report, _source_snapshot_list(snapshots), listed, errors)

    if comparisons_given or trend_given:
        # When only comparisons are given the report's `trend.source` may
        # legitimately be either label for the same summary.
        ignore = ("source",) if not trend_given else ()
        _diff_into("trend", report.get("trend"), expected["trend"], errors, ignore=ignore)
    if comparisons_given:
        _diff_into("trend_validation", report.get("trend_validation"),
                   expected["trend_validation"], errors)
        # Prompt 528: the report's trend against what the given comparisons
        # produce, one specific code per kind of disagreement.
        _check_trend_against_source_comparisons(
            "trend", _judged_trend_summary(report.get("trend"), report.get("trend_validation")),
            summarize_learned_knowledge_diagnostic_snapshot_comparison_trend(listed), len(listed),
            False, errors)

    # Prompt 522: the filtered trend sections, when filtered sources were
    # given. (A reversed filtered chronology is a state Prompt 520 reports,
    # not an ordering error, so the filtered comparisons' order is not
    # judged here.)
    if filtered_comparisons is not _NOT_PROVIDED or filtered_trend_summary is not _NOT_PROVIDED:
        filtered_comparisons_given = filtered_comparisons is not _NOT_PROVIDED
        filtered_trend_given = (
            filtered_trend_summary is not _NOT_PROVIDED and filtered_trend_summary is not None)
        if (filtered_comparisons_given and filtered_comparisons is not None
                and not isinstance(filtered_comparisons, (list, tuple))):
            errors.append("invalid_source:filtered_comparisons")
            filtered_comparisons_given = False
        if "filtered_trend" not in report:
            errors.append("source_mismatch:filtered_trend")
        else:
            expected_trend, expected_validation = _report_filtered_trend_sections(
                filtered_comparisons if filtered_comparisons_given else None, filtered_trend_summary)
            if filtered_comparisons_given or filtered_trend_given:
                ignore = ("source",) if not filtered_trend_given else ()
                _diff_into("filtered_trend", report.get("filtered_trend"), expected_trend, errors,
                           ignore=ignore)
            if filtered_comparisons_given:
                _diff_into("filtered_trend_validation", report.get("filtered_trend_validation"),
                           expected_validation, errors)
                listed_filtered = list(filtered_comparisons) if filtered_comparisons else []
                _check_trend_against_source_comparisons(
                    "filtered_trend", _judged_trend_summary(
                        report.get("filtered_trend"), report.get("filtered_trend_validation")),
                    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend(listed_filtered),
                    len(listed_filtered), True, errors)
    return errors


# ----------------------------------------------------------------------
# Prompt 526 - consistency of "selected_sections" metadata
# ----------------------------------------------------------------------
# `validate_learned_knowledge_diagnostic_report()` can additionally be
# handed the metadata describing which sections of the report a caller
# selected, and verifies it against itself and against the report. It is
# the same read-only check the rest of this validator is - the report is
# never repaired, regenerated or mutated, and nothing is scored.
#
# The metadata is a dict carrying the four lists Prompt 516's section
# filter already uses (any other key in it is not judged):
#
#     {"requested_sections": [...], "included_sections": [...],
#      "unavailable_sections": [...], "unknown_sections": [...]}
#
# The selectable sections are the report's own - `snapshots`,
# `comparison`, `comparison_validation`, `trend`, `trend_validation`
# and, for a report built with them (Prompt 522), the filtered
# `filtered_trend` and `filtered_trend_validation`. A section the report
# does not have data for is *unavailable*; a name that is not one of
# those seven at all is *unknown* - the two are never merged. (Prompt
# 515/516 summary section names such as `"rates"` are a different
# vocabulary and are unknown here; only `"trend"` exists in both.)
#
# "Corresponding report data" for a section is exactly what Prompt 513
# puts there: the section is a dict, `available` is `True`, and its
# payload (`latest` / `summary` / `result`) is not `None`. "Present and
# valid" means that and additionally passing the very same per-section
# checks `_validate_report_structure()` applies to it (shape, count,
# payload presence, validation-result agreement, ...) - a section whose
# own problems the report already flags is not flagged a second time
# here. Error codes, in a fixed order:
#
#   invalid_type:selected_sections                    not a dict
#   missing_field:selected_sections.<field>           one of the 4 lists absent
#   invalid_type:selected_sections.<field>            ... or not a list
#   duplicate_section:<field>:<name>                  a name repeated in one list
#   unknown_section_marked_included:<name>            included, not a real section
#   unknown_section_marked_unavailable:<name>         unavailable, not a real section
#   known_section_marked_unknown:<name>               a real section listed as unknown
#   section_not_requested:<included|unavailable|unknown>:<name>
#   section_included_and_unavailable:<name>           both at once
#   included_section_without_data:<name>              included, no data in the report
#   unavailable_section_present:<name>                unavailable, yet present and valid
#   requested_section_unaccounted:<name>              requested, in none of the 3 lists
#
# Malformed metadata (not a dict / a list missing or not a list) is
# reported alone: its lists cannot be judged against each other.
# These errors make `valid` `False` but leave `well_formed` as it is - a
# report is not malformed because caller-supplied metadata about it is
# wrong, the same way a source mismatch does not make it malformed.

_SELECTED_SECTION_METADATA_FIELDS = (
    "requested_sections", "included_sections", "unavailable_sections", "unknown_sections",
)
_SELECTABLE_REPORT_SECTIONS = _REPORT_SECTIONS + _REPORT_FILTERED_SECTIONS
_SELECTED_SECTION_PAYLOAD_FIELDS = {
    "snapshots": "latest",
    "comparison": "latest",
    "comparison_validation": "result",
    "trend": "summary",
    "trend_validation": "result",
    "filtered_trend": "summary",
    "filtered_trend_validation": "result",
}
# validation section -> (component it judges, component payload field,
# the existing recompute check `_validate_report_structure()` uses).
_SELECTED_SECTION_VALIDATION_JUDGES = {
    "comparison_validation": ("comparison", "latest", _comparison_validation_problem),
    "trend_validation": ("trend", "summary", _trend_validation_problem),
    "filtered_trend_validation": (
        "filtered_trend", "summary", _filtered_trend_validation_problem),
}
_SELECTED_SECTION_LOCAL_CHECKS = {
    "snapshots": _check_snapshots_section,
    "comparison": _check_comparison_section,
    "trend": _check_trend_section,
    "filtered_trend": _check_filtered_trend_section,
}


def _selectable_section_name(name):
    return isinstance(name, str) and name in _SELECTABLE_REPORT_SECTIONS


def _selected_name_in(name, names):
    """`name in names`, where two names match only with the same type and
    equality (so `1`, `1.0` and `True` are never merged)."""
    return any(type(other) is type(name) and other == name for other in names)


def _selected_duplicates(names):
    """The names repeated in `names`, each once, in first-repeat order."""
    seen = []
    repeated = []
    for name in names:
        if _selected_name_in(name, seen):
            if not _selected_name_in(name, repeated):
                repeated.append(name)
        else:
            seen.append(name)
    return repeated


def _selected_section_has_data(report, name):
    """Whether the report carries data for `name`: the section is a dict,
    marked available, with a non-`None` payload."""
    section = report.get(name)
    return (
        isinstance(section, dict) and section.get("available") is True
        and section.get(_SELECTED_SECTION_PAYLOAD_FIELDS[name]) is not None)


def _selected_section_is_valid(report, name):
    """Whether `name` passes the same per-section checks
    `_validate_report_structure()` applies to it (into a throwaway error
    list - this never adds to the report's own errors)."""
    errors = []
    section = _report_section_shape(report, name, errors)
    if section is not None:
        if name in _SELECTED_SECTION_LOCAL_CHECKS:
            _SELECTED_SECTION_LOCAL_CHECKS[name](section, errors)
        else:
            component, payload_field, problem = _SELECTED_SECTION_VALIDATION_JUDGES[name]
            component_section = _report_section_shape(report, component, [])
            _check_validation_section(
                name, component, component_section, payload_field, section, problem, errors)
    return not errors


def _check_selected_sections(report, selected_sections):
    """Errors (in a fixed order) for `selected_sections` metadata that is
    inconsistent with itself or with `report` (a dict). Never mutates
    either."""
    if not isinstance(selected_sections, dict):
        return ["invalid_type:selected_sections"]
    errors = []
    for field in _SELECTED_SECTION_METADATA_FIELDS:
        if field not in selected_sections:
            errors.append("missing_field:selected_sections.%s" % field)
        elif not isinstance(selected_sections[field], list):
            errors.append("invalid_type:selected_sections.%s" % field)
    if errors:
        return errors

    requested = selected_sections["requested_sections"]
    included = selected_sections["included_sections"]
    unavailable = selected_sections["unavailable_sections"]
    unknown = selected_sections["unknown_sections"]

    for field in _SELECTED_SECTION_METADATA_FIELDS:
        for name in _selected_duplicates(selected_sections[field]):
            errors.append("duplicate_section:%s:%s" % (field, _filter_name_text(name)))

    for name in _filter_dedupe(included):
        text = _filter_name_text(name)
        if not _selectable_section_name(name):
            errors.append("unknown_section_marked_included:%s" % text)
            continue
        if not _selected_name_in(name, requested):
            errors.append("section_not_requested:included:%s" % text)
        if _selected_name_in(name, unavailable):
            errors.append("section_included_and_unavailable:%s" % text)
        if not _selected_section_has_data(report, name):
            errors.append("included_section_without_data:%s" % text)

    for name in _filter_dedupe(unavailable):
        text = _filter_name_text(name)
        if not _selectable_section_name(name):
            errors.append("unknown_section_marked_unavailable:%s" % text)
            continue
        if not _selected_name_in(name, requested):
            errors.append("section_not_requested:unavailable:%s" % text)
        if _selected_section_has_data(report, name) and _selected_section_is_valid(report, name):
            errors.append("unavailable_section_present:%s" % text)

    for name in _filter_dedupe(unknown):
        text = _filter_name_text(name)
        if _selectable_section_name(name):
            errors.append("known_section_marked_unknown:%s" % text)
        if not _selected_name_in(name, requested):
            errors.append("section_not_requested:unknown:%s" % text)

    for name in _filter_dedupe(requested):
        if not (_selected_name_in(name, included) or _selected_name_in(name, unavailable)
                or _selected_name_in(name, unknown)):
            errors.append("requested_section_unaccounted:%s" % _filter_name_text(name))
    return errors


# Prompt 530 - every given snapshot against its own validation state.
# The report validator already judged the report's LATEST snapshot with
# `_snapshot_structural_errors()`; the other snapshots of a given source
# history, and the filtered summary snapshots (Prompt 517), were never
# judged. Here each one is held to the existing structural check for its
# kind - which itself reuses the Prompt 506 analysis validator and states
# what a `"valid"` / `"invalid"` snapshot must and must not contain - and
# a filtered comparison that says it is valid is held to the filtered
# snapshots it names by re-running the existing Prompt 519 validator with
# them. Read-only: nothing is repaired, regenerated or scored.


def _source_filtered_snapshot_list(filtered_snapshots):
    if isinstance(filtered_snapshots, LearnedKnowledgeFilteredSummarySnapshotHistory):
        return filtered_snapshots.get_all()
    return list(filtered_snapshots) if isinstance(filtered_snapshots, (list, tuple)) else []


def _find_related_filtered_snapshot(snapshot_list, identity):
    """Prompt 535. The snapshot in `snapshot_list` that `identity` names
    - exactly (id and sequence), or else the first one with the same
    `snapshot_id` but a different `sequence` (an identity that
    contradicts the snapshot it points at: an id always carries its own
    sequence and sequences are never reused, so this is never an honest
    miss). `None` when the identity is unusable or names none of them: a
    snapshot that is simply not in the list - including an unrelated
    one that merely shares a sequence number - is still a missing
    state, never guessed at."""
    exact = _find_source_snapshot(snapshot_list, identity)
    if exact is not None:
        return exact
    if not isinstance(identity, dict):
        return None
    reference = {key: identity.get(key) for key in ("snapshot_id", "sequence")}
    if not _identity_is_well_formed(reference):
        return None
    for snapshot in snapshot_list:
        if isinstance(snapshot, dict) and snapshot.get("snapshot_id") == reference["snapshot_id"]:
            return snapshot
    return None


def _filtered_comparison_source_problems(comparison, snapshot_list):
    """Errors the existing Prompt 519 validator adds for `comparison` when
    it is also given the filtered snapshots it names, beyond what it
    reports without them. Empty when the comparison is not marked valid,
    or when either snapshot is not among `snapshot_list` (a missing
    state, never guessed at). Prompt 535: a snapshot that the
    comparison's identity contradicts (same id or sequence, not both) is
    not missing - it is held to the comparison and reported as an
    identity mismatch."""
    if not isinstance(comparison, dict) or comparison.get("valid") is not True:
        return []
    earlier = _find_related_filtered_snapshot(snapshot_list, comparison.get("earlier"))
    later = _find_related_filtered_snapshot(snapshot_list, comparison.get("later"))
    if earlier is None or later is None:
        return []
    alone = validate_learned_knowledge_filtered_summary_snapshot_comparison(comparison)["errors"]
    with_sources = validate_learned_knowledge_filtered_summary_snapshot_comparison(
        comparison, earlier, later)["errors"]
    return [code for code in with_sources if code not in alone]


def _check_snapshot_states(report, snapshots, filtered_snapshots, filtered_comparisons, errors):
    """Prompt 530. Errors, in a fixed order:

      snapshot_inconsistent:<index>:<snapshot code>
          a given diagnostic snapshot other than the last (the last is
          the report's own `snapshots.latest`, judged - and reported as
          `snapshots.latest:<code>` - by the structural checks) is
          malformed, or its data contradicts its validation state
      invalid_source:filtered_snapshots
      filtered_snapshot_inconsistent:<index>:<filtered snapshot code>
          the same for a Prompt 517 filtered snapshot (every one)
      filtered_comparison_source_inconsistent:<index>:<519 code>
      claims_valid_but_source_invalid:filtered_comparison_sources
          a filtered comparison marked valid contradicts the filtered
          snapshots it names, and the report's filtered trend validation
          still calls its comparisons valid
    """
    if (snapshots is not _NOT_PROVIDED and isinstance(
            snapshots, (LearnedKnowledgeDiagnosticSnapshotHistory, list))):
        listed = _source_snapshot_list(snapshots)
        for index, snapshot in enumerate(listed[:-1]):
            for code in _snapshot_structural_errors(snapshot):
                errors.append("snapshot_inconsistent:%d:%s" % (index, code))

    if filtered_snapshots is _NOT_PROVIDED or filtered_snapshots is None:
        return
    if not isinstance(filtered_snapshots, (
            LearnedKnowledgeFilteredSummarySnapshotHistory, list, tuple)):
        errors.append("invalid_source:filtered_snapshots")
        return
    snapshot_list = _source_filtered_snapshot_list(filtered_snapshots)
    for index, snapshot in enumerate(snapshot_list):
        for code in _filtered_summary_snapshot_structural_errors(snapshot):
            errors.append("filtered_snapshot_inconsistent:%d:%s" % (index, code))

    if filtered_comparisons is _NOT_PROVIDED or not isinstance(filtered_comparisons, (list, tuple)):
        return
    found = False
    for index, comparison in enumerate(filtered_comparisons):
        for code in _filtered_comparison_source_problems(comparison, snapshot_list):
            found = True
            errors.append("filtered_comparison_source_inconsistent:%d:%s" % (index, code))
    section = report.get("filtered_trend_validation")
    result = section.get("result") if isinstance(section, dict) else None
    if (found and isinstance(result, dict) and result.get("valid") is True
            and section.get("available") is True):
        errors.append("claims_valid_but_source_invalid:filtered_comparison_sources")


# Prompt 532 - consistency between the report and its Prompt 515/516
# human-readable diagnostic summary
# ----------------------------------------------------------------------
# `validate_learned_knowledge_diagnostic_report()` can additionally be
# handed the human-readable summary a caller built for `report` -
# `format_learned_knowledge_diagnostic_summary()`'s (Prompt 515) result,
# and/or the section-filtered summary built from THAT
# (`filter_learned_knowledge_diagnostic_summary()`'s, Prompt 516, result)
# - and verifies each is what the existing, unmodified Prompt 515/516
# functions themselves would have produced. Nothing here is a second
# summary system: the "expected" summary is obtained by calling
# `format_learned_knowledge_diagnostic_summary(report, core_validation)`
# (`core_validation` being this same validator's own structural/source
# judgement of `report`, computed above, before this check runs) and,
# for the filtered summary, by calling
# `filter_learned_knowledge_diagnostic_summary()` on that expected
# summary with the very `"requested_sections"` the given filtered
# summary itself claims to have used. Both calls are made only to
# compare against - never to replace - what the caller handed in;
# `report`, `summary` and `filtered_summary` are never mutated, and
# nothing is repaired or regenerated for any other purpose.
#
# Error codes, `<name>` being `summary` or `filtered_summary`:
#
#   invalid_source:<name>                     not a dict
#   claims_valid_but_source_invalid:<name>     says "valid" while the
#                                               recomputed summary is
#                                               "invalid" (a summary
#                                               claiming valid data over
#                                               an invalid report)
#   claims_invalid_but_source_valid:<name>     says "invalid" while the
#                                               recomputed summary is
#                                               "valid"
#   mismatched_validation_result:<name>        `report_validity` differs
#                                               some other way (neither
#                                               of the above - e.g. an
#                                               unrecognized value)
#   source_mismatch:<name>.<field>...          any other field - most
#                                               importantly
#                                               `available_sections` /
#                                               `unavailable_sections` /
#                                               `metrics` - disagrees
#                                               with the recomputed
#                                               summary, one level of
#                                               detail below `metrics`'s
#                                               own per-section values
#                                               (the same depth
#                                               `_diff_into()` already
#                                               uses for every other
#                                               source comparison here)
#
# An unavailable/missing report component stays exactly that in the
# recomputed summary too (Prompt 515 already never fabricates a value
# for one), so a summary that correctly reports a section as
# unavailable is never flagged - only a summary that CONTRADICTS what
# the report actually has (claims a section available that is not, or
# vice versa, or carries the wrong metrics for one) is. Both sources are
# entirely optional and independent of every other optional source this
# validator takes; when neither is given nothing about a summary is
# checked. These errors are added after the existing source/snapshot-
# state checks and before `selected_sections` (whose errors still come
# last, unchanged). No new metric or analysis is computed - every value
# compared already exists in `report`/`summary`/`filtered_summary` or is
# the exact, unmodified Prompt 515/516 recomputation of it.
#
# ----------------------------------------------------------------------
# Prompt 533 - a filtered diagnostic summary against its actual source
# summary (not one recomputed from a report)
# ----------------------------------------------------------------------
# The check above already holds `filtered_summary` to a summary
# recomputed from `report`. When the caller also hands in the actual
# `summary` the filtered one claims to have been filtered from, this
# additionally holds `filtered_summary` directly to THAT summary -
# `filtered_summary`'s real, immediate source - independent of whatever
# the report itself says. It reuses the exact same, unmodified Prompt
# 516 `filter_learned_knowledge_diagnostic_summary()` to build the value
# `filtered_summary` should be for `summary`'s own `requested_sections`,
# and the same `_check_recomputed_summary()`/`_diff_into()` machinery
# every other source cross-check in this validator already uses -
# nothing here is a new comparison mechanism, metric, or analysis.
#
# This is what verifies, concretely:
#   - every section `filtered_summary` marks `included` actually exists,
#     available, in `summary` (an included section `summary` never
#     offered is a `source_mismatch:filtered_summary_source.
#     included_sections`/`...metrics.<section>`);
#   - a section `summary` does not offer stays `unavailable`, never
#     silently promoted to `included`;
#   - a name that is not a real summary section at all
#     (`unknown_sections`) is never instead reported `included` or
#     `unavailable`;
#   - `requested_sections`/`included_sections`/`unavailable_sections`/
#     `unknown_sections` agree with each other and with `summary`, the
#     same way `filter_learned_knowledge_diagnostic_summary()` itself
#     guarantees they would for a correctly-filtered result;
#   - every included value (including a filtered `trend` section, where
#     present) is exactly the corresponding value in `summary`, not a
#     modified or mismatched one;
#   - `summary`'s own `"valid"`/`"invalid"` state, and an unavailable or
#     missing section, are preserved rather than re-derived - an empty
#     or entirely-invalid `summary` is judged the same way
#     `filter_learned_knowledge_diagnostic_summary()` itself judges one.
#
# Error codes, using the same `<name>` = `filtered_summary_source`
# convention `_check_recomputed_summary()` already uses for every other
# name it is given:
#
#   claims_valid_but_source_invalid:filtered_summary_source
#   claims_invalid_but_source_valid:filtered_summary_source
#   mismatched_validation_result:filtered_summary_source
#   source_mismatch:filtered_summary_source.<field>...
#
# Only runs when both `summary` and `filtered_summary` are given (a
# `filtered_summary` given alone has no actual source to hold it to
# beyond the report-recomputed one already checked above; a `summary`
# given alone has no filtered summary to check). Never mutates `summary`
# or `filtered_summary`; no new metric or analysis is computed; fully
# deterministic; every other existing behavior and API is unchanged.

def _check_filtered_summary_against_source(summary, filtered_summary, errors):
    """Cross-checks `filtered_summary` (a Prompt 516 result) directly
    against `summary` (the Prompt 515 result it is actually filtered
    from), independent of any report. Reuses the exact, unmodified
    `filter_learned_knowledge_diagnostic_summary()` to build the value
    `filtered_summary` should be for `summary`'s own
    `"requested_sections"`, then diffs the two. Only called when
    `filtered_summary` is a dict (a malformed one is already reported
    once by the caller); never mutates `summary` or `filtered_summary`."""
    if not isinstance(filtered_summary, dict):
        return
    expected = filter_learned_knowledge_diagnostic_summary(
        summary, filtered_summary.get("requested_sections"))
    _check_recomputed_summary("filtered_summary_source", filtered_summary, expected, errors)


# ----------------------------------------------------------------------
# Prompt 534 - a filtered diagnostic snapshot against its filtered
# diagnostic summary
# ----------------------------------------------------------------------
# A Prompt 517 filtered-summary snapshot is built ONLY from a Prompt 516
# filtered summary. When the caller hands `validate_learned_knowledge_
# diagnostic_report()` both the `filtered_snapshot` and the
# `filtered_summary` it was recorded from, this verifies the two still
# agree. Nothing here is a second snapshot/summary system: the value the
# snapshot should be is obtained by calling the existing, unmodified
# `_build_filtered_summary_snapshot()` (the very builder
# `LearnedKnowledgeFilteredSummarySnapshotHistory.record_filtered_
# summary()` uses) on the given `filtered_summary`, and the given
# snapshot is compared against it with the same `_diff_into()` /
# `_summary_validity_problem()` machinery every other source cross-check
# in this validator already uses. Neither input is mutated, repaired, or
# regenerated for any other purpose; no new metric or analysis exists.
#
# Checked, per real summary section (fixed Prompt 515 order):
#   - the snapshot only lists a section as included when the filtered
#     summary really has it available (and vice versa);
#   - an unavailable section stays unavailable, and an unavailable
#     versus a missing section is never conflated;
#   - the number of unknown names agrees (their text is never stored);
#   - every shared section value - including a filtered `trend` -
#     matches exactly, and the validity/validation errors agree.
#
# Error codes (all after the Prompt 532/533 ones, before
# `selected_sections`'s):
#
#   invalid_source:filtered_snapshot
#   filtered_snapshot_inconsistent:<code>       the snapshot is itself
#                                               malformed (existing
#                                               Prompt 530 codes)
#   filtered_snapshot_section_not_available_in_summary:<section>
#   filtered_summary_section_not_available_in_snapshot:<section>
#   filtered_snapshot_section_state_mismatch:<section>
#   filtered_snapshot_unknown_section_count_mismatch
#   claims_valid_but_source_invalid:filtered_snapshot_summary
#   claims_invalid_but_source_valid:filtered_snapshot_summary
#   mismatched_validation_result:filtered_snapshot_summary
#   source_mismatch:filtered_snapshot_summary.validation_errors
#   source_mismatch:filtered_snapshot_summary.metrics.<section>[.<field>]
#
# Only runs when both `filtered_snapshot` and `filtered_summary` are
# given (`None` counts as not given: a missing snapshot is a missing
# state, never guessed at). Deterministic; every existing behavior and
# API is unchanged.

def _filtered_snapshot_section_state(included, unavailable, section):
    if section in included:
        return "included"
    if section in unavailable:
        return "unavailable"
    return "missing"


def _check_filtered_snapshot_against_summary(filtered_snapshot, filtered_summary, errors):
    """Prompt 534. Cross-checks `filtered_snapshot` (a Prompt 517
    snapshot) against `filtered_summary` (the Prompt 516 result it was
    recorded from). `filtered_summary` must already be a dict (a
    non-dict one is reported once by the caller). Never mutates or
    repairs either; never raises."""
    if not isinstance(filtered_snapshot, dict):
        errors.append("invalid_source:filtered_snapshot")
        return
    structural = _filtered_summary_snapshot_structural_errors(filtered_snapshot)
    if structural:
        # Not a well-formed snapshot: nothing in it is trusted enough to
        # compare, so only why it is malformed is reported.
        errors.extend("filtered_snapshot_inconsistent:%s" % code for code in structural)
        return

    expected = _build_filtered_summary_snapshot(filtered_summary, filtered_snapshot["sequence"])
    actual_included = filtered_snapshot["included_sections"]
    actual_unavailable = filtered_snapshot["unavailable_sections"]
    expected_included = expected["included_sections"]
    expected_unavailable = expected["unavailable_sections"]
    actual_metrics = filtered_snapshot["metrics"]
    expected_metrics = expected["metrics"]

    for section in _SUMMARY_SECTIONS:
        actual_state = _filtered_snapshot_section_state(actual_included, actual_unavailable, section)
        expected_state = _filtered_snapshot_section_state(
            expected_included, expected_unavailable, section)
        if actual_state != expected_state:
            if actual_state == "included":
                errors.append(
                    "filtered_snapshot_section_not_available_in_summary:%s" % section)
            elif expected_state == "included":
                errors.append(
                    "filtered_summary_section_not_available_in_snapshot:%s" % section)
            else:
                errors.append("filtered_snapshot_section_state_mismatch:%s" % section)
            continue
        if actual_state == "missing":
            if actual_metrics.get(section) is not None:
                _diff_into("filtered_snapshot_summary.metrics.%s" % section,
                           actual_metrics.get(section), None, errors, depth=1)
            continue
        _diff_into("filtered_snapshot_summary.metrics.%s" % section,
                   actual_metrics.get(section), expected_metrics.get(section), errors, depth=1)

    if filtered_snapshot["unknown_section_count"] != expected["unknown_section_count"]:
        errors.append("filtered_snapshot_unknown_section_count_mismatch")

    problem = _summary_validity_problem(
        filtered_snapshot["validation_status"], expected["validation_status"])
    if problem is not None:
        errors.append("%s:filtered_snapshot_summary" % problem)
    if filtered_snapshot["validation_errors"] != expected["validation_errors"]:
        errors.append("source_mismatch:filtered_snapshot_summary.validation_errors")


def _summary_validity_problem(actual_validity, expected_validity):
    """`None` when `actual_validity` (a `report_validity` value read off
    the given summary/filtered summary) agrees with `expected_validity`
    (the same field on the freshly recomputed one); else the specific
    disagreement code, without the trailing `:<name>` suffix."""
    if actual_validity == expected_validity:
        return None
    if actual_validity == REPORT_VALIDITY_VALID and expected_validity == REPORT_VALIDITY_INVALID:
        return "claims_valid_but_source_invalid"
    if actual_validity == REPORT_VALIDITY_INVALID and expected_validity == REPORT_VALIDITY_VALID:
        return "claims_invalid_but_source_valid"
    return "mismatched_validation_result"


def _check_recomputed_summary(name, actual, expected, errors):
    """Errors for how `actual` (a given Prompt 515/516 result) differs
    from `expected` (the fresh, unmodified recomputation of it). Never
    mutates either. `name` is `"summary"` or `"filtered_summary"`."""
    if not isinstance(actual, dict):
        errors.append("invalid_source:%s" % name)
        return
    problem = _summary_validity_problem(actual.get("report_validity"), expected.get("report_validity"))
    if problem is not None:
        errors.append("%s:%s" % (problem, name))
    _diff_into(name, actual, expected, errors, ignore=("report_validity",))


def _check_report_against_summaries(report, core_validation, summary, filtered_summary, errors,
                                    filtered_snapshot=_NOT_PROVIDED):
    """Prompt 532. Cross-checks the given `summary`/`filtered_summary`
    against what the existing, unmodified Prompt 515/516 functions
    produce for `report` and `core_validation` (this validator's own
    judgement of `report`, computed before this runs). Sources not given
    are not checked; never mutates `report`, `summary`, `filtered_summary`
    or `core_validation`."""
    expected_summary = format_learned_knowledge_diagnostic_summary(report, core_validation)
    if summary is not _NOT_PROVIDED:
        _check_recomputed_summary("summary", summary, expected_summary, errors)
    if filtered_summary is not _NOT_PROVIDED:
        if not isinstance(filtered_summary, dict):
            errors.append("invalid_source:filtered_summary")
        else:
            expected_filtered = filter_learned_knowledge_diagnostic_summary(
                expected_summary, filtered_summary.get("requested_sections"))
            _check_recomputed_summary("filtered_summary", filtered_summary, expected_filtered, errors)
            if summary is not _NOT_PROVIDED:
                # Prompt 533: also hold `filtered_summary` directly to the
                # actual `summary` given (its real source), not only to
                # the report-recomputed one checked just above.
                _check_filtered_summary_against_source(summary, filtered_summary, errors)
            if filtered_snapshot is not _NOT_PROVIDED and filtered_snapshot is not None:
                # Prompt 534: the filtered snapshot recorded from
                # `filtered_summary` must still agree with it.
                _check_filtered_snapshot_against_summary(
                    filtered_snapshot, filtered_summary, errors)


def validate_learned_knowledge_diagnostic_report(
        report, snapshots=_NOT_PROVIDED, comparisons=_NOT_PROVIDED, trend_summary=_NOT_PROVIDED,
        filtered_comparisons=_NOT_PROVIDED, filtered_trend_summary=_NOT_PROVIDED,
        selected_sections=_NOT_PROVIDED, filtered_snapshots=_NOT_PROVIDED,
        summary=_NOT_PROVIDED, filtered_summary=_NOT_PROVIDED, filtered_snapshot=_NOT_PROVIDED):
    """Deterministic, read-only validation of `report` - the dict
    `build_learned_knowledge_diagnostic_report()` (Prompt 513) returns.
    Returns a new, independent dict in the same style as the Prompt 506,
    510 and 512 validators:

        {
            "valid": <bool>,        # fully valid report
            "well_formed": <bool>,  # internally consistent on its own
            "errors": [<str>, ...],
            "warnings": [],         # always a list (empty today)
        }

    `valid` is `True` exactly when `errors` is empty; an invalid report
    always carries at least one structured error code, in a fixed check
    order (structural / internal-consistency codes first, then the codes
    that come from comparing against the given sources). `well_formed` is
    `False` when the report is malformed or contradicts itself; a report
    can be well-formed yet not fully valid when the optional sources are
    given and the report does not match them (`"source_mismatch:<path>"`).
    See the module-level note above for exactly what is checked; error
    codes are short strings such as `"missing_field:<name>"`,
    `"invalid_type:<path>"`, `"unsupported_status_value:structural_status"`,
    `"inconsistent_structural_status"`, `"claims_valid_but_source_invalid:
    <snapshot|comparison|trend>"`, `"fabricated_value_for_unavailable_
    component:<path>"`, `"metric_mismatch:<pair>:<field>"`,
    `"invalid_chronological_ordering:<where>"`, `"snapshots.latest:
    <snapshot error>"`, `"source_mismatch:<path>"`.

    Optional sources - the same arguments the report was built from:
    `snapshots` (`None`, a `LearnedKnowledgeDiagnosticSnapshotHistory`, or
    an oldest-first list), `comparisons` (`None` or an oldest-first
    list), `trend_summary` (`None` or a trend summary dict). A source that
    is not given is simply not cross-checked. Prompt 522 adds two more,
    for a report built with the filtered trend: `filtered_comparisons`
    (`None` or an oldest-first list of Prompt 518 comparisons) and
    `filtered_trend_summary` (`None` or a Prompt 520 summary).

    Prompt 526 adds `selected_sections`: optional metadata (a dict with
    `requested_sections` / `included_sections` / `unavailable_sections` /
    `unknown_sections` lists) describing which of the report's sections
    were selected. When given it is verified for internal consistency
    and against the report's own section data - see the "Prompt 526"
    note above; anything but a dict (including `None`) is an
    `"invalid_type:selected_sections"` error, and when it is not given
    nothing about selection is checked. Its errors come last, make
    `valid` `False`, and do not change `well_formed`.

    Prompt 530 verifies snapshot validation states against snapshot
    data. Given `snapshots`, every snapshot of the source history (not
    only the latest) must be structurally sound for the state it claims -
    a `"valid"` snapshot carries a valid Prompt 506 analysis and no
    validation errors, an `"invalid"` one carries no analysis values -
    reported as `"snapshot_inconsistent:<index>:<code>"`. The new
    optional `filtered_snapshots` (`None`, a
    `LearnedKnowledgeFilteredSummarySnapshotHistory`, or an oldest-first
    list of Prompt 517 snapshots) gets the same judgement
    (`"filtered_snapshot_inconsistent:<index>:<code>"`), and, together
    with `filtered_comparisons`, each filtered comparison marked valid is
    held to the filtered snapshots it names
    (`"filtered_comparison_source_inconsistent:<index>:<code>"`,
    `"claims_valid_but_source_invalid:filtered_comparison_sources"`).
    Missing / unavailable snapshots are not errors; sources that are not
    given are not checked. These errors come after the source errors.

    Prompt 532 verifies consistency between the report and a Prompt 515
    human-readable summary of it, and/or a Prompt 516 section-filtered
    summary of that. `summary` (`None` or a `format_learned_knowledge_
    diagnostic_summary()` result) and `filtered_summary` (`None` or a
    `filter_learned_knowledge_diagnostic_summary()` result) are each
    checked, independently, against what the existing Prompt 515/516
    functions themselves produce for `report`. A summary claiming
    `"valid"` over an invalid report is `"claims_valid_but_source_
    invalid:summary"` (`"...:filtered_summary"` for the filtered one);
    the reverse is `"claims_invalid_but_source_valid:<name>"`; any other
    `report_validity` disagreement is `"mismatched_validation_result:
    <name>"`; any other field that disagrees - most importantly
    `available_sections` / `unavailable_sections` / `metrics` - is
    `"source_mismatch:<name>.<field>..."`. A section the report has no
    data for stays unavailable in both without being flagged; only a
    summary that contradicts what the report actually has is. Neither
    argument is required by the other or by any other optional source.
    These errors come after the source/snapshot-state errors above and
    before `selected_sections`'s (still last, unchanged).

    Prompt 533 additionally holds `filtered_summary` directly to
    `summary` itself - its actual, immediate source - whenever both are
    given, not only to the report-recomputed summary above. It reuses
    the same, unmodified `filter_learned_knowledge_diagnostic_summary()`
    on `summary` with `filtered_summary`'s own `"requested_sections"`,
    and the same comparison machinery, so an included section that
    `summary` never offered, a real section quietly promoted out of
    `"unavailable_sections"`, an unknown name reported as included or
    unavailable instead of unknown, or a filtered value (a filtered
    `"trend"`, included) that no longer matches `summary`'s own value is
    `"source_mismatch:filtered_summary_source.<field>..."`; a validity
    disagreement is `"claims_valid_but_source_invalid:
    filtered_summary_source"` / `"claims_invalid_but_source_valid:
    filtered_summary_source"` / `"mismatched_validation_result:
    filtered_summary_source"`. `summary`'s own valid/invalid/unavailable/
    missing states are preserved, never re-derived. These errors are
    added alongside the Prompt 532 ones above (same ordering).

    Prompt 534 additionally verifies a Prompt 517 filtered snapshot
    against the Prompt 516 filtered summary it was recorded from, when
    both `filtered_snapshot` (`None` or one snapshot dict) and
    `filtered_summary` are given. The snapshot may only list a section
    as included when the filtered summary has it available (and the
    reverse), an unavailable section stays unavailable (never conflated
    with a missing one), the unknown-name count agrees, and every shared
    section value - a filtered `"trend"` included - matches exactly:
    `"filtered_snapshot_section_not_available_in_summary:<section>"`,
    `"filtered_summary_section_not_available_in_snapshot:<section>"`,
    `"filtered_snapshot_section_state_mismatch:<section>"`,
    `"filtered_snapshot_unknown_section_count_mismatch"`,
    `"source_mismatch:filtered_snapshot_summary.metrics.<section>..."`,
    and the validity codes with the `filtered_snapshot_summary` name. A
    malformed snapshot is `"filtered_snapshot_inconsistent:<code>"`
    (`"invalid_source:filtered_snapshot"` when not a dict). The expected
    snapshot is built by the existing `_build_filtered_summary_snapshot()`;
    neither input is mutated or repaired. These errors come after the
    Prompt 532/533 ones, before `selected_sections`'s.

    Never repairs, regenerates for any purpose other than the optional
    source comparison, or otherwise changes `report`, `snapshots`,
    `comparisons`, `trend_summary`, or any validation result inside them;
    a non-dict `report` (including `None` and `{}`) safely yields a
    structured error (`"report_not_a_dict"` / `"missing_field:<name>"`s).
    Not called anywhere in the gate/decision/response path, and it does
    not score, rank, classify, or interpret a report. Deterministic: the
    same inputs always give an equal result.
    """
    if not isinstance(report, dict):
        return {"valid": False, "well_formed": False, "errors": ["report_not_a_dict"], "warnings": []}

    structural = _validate_report_structure(report)
    source_errors = []
    if (snapshots is not _NOT_PROVIDED or comparisons is not _NOT_PROVIDED
            or trend_summary is not _NOT_PROVIDED
            or filtered_comparisons is not _NOT_PROVIDED
            or filtered_trend_summary is not _NOT_PROVIDED):
        source_errors = _check_report_against_sources(
            report, snapshots, comparisons, trend_summary,
            filtered_comparisons, filtered_trend_summary)
    if snapshots is not _NOT_PROVIDED or filtered_snapshots is not _NOT_PROVIDED:
        # Prompt 530: snapshot validation states against snapshot data.
        _check_snapshot_states(report, snapshots, filtered_snapshots, filtered_comparisons,
                               source_errors)

    errors = structural + [item for item in source_errors if item not in structural]
    if summary is not _NOT_PROVIDED or filtered_summary is not _NOT_PROVIDED:
        # Prompt 532: consistency with the Prompt 515/516 human-readable
        # (filtered) summary, judged against this validator's own
        # structural/source verdict on `report` so far.
        core_validation = {
            "valid": not errors, "well_formed": not structural, "errors": list(errors), "warnings": [],
        }
        summary_errors = []
        _check_report_against_summaries(report, core_validation, summary, filtered_summary,
                                        summary_errors, filtered_snapshot)
        errors += [item for item in summary_errors if item not in errors]
    if selected_sections is not _NOT_PROVIDED:
        errors += [item for item in _check_selected_sections(report, selected_sections)
                   if item not in errors]
    return {"valid": not errors, "well_formed": not structural, "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 515 - human-readable summary of a Prompt 513 unified diagnostic
# report, judged by its own Prompt 514 validation result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY presentation layer over the dict
# `build_learned_knowledge_diagnostic_report()` (Prompt 513) returns,
# using the dict `validate_learned_knowledge_diagnostic_report()`
# (Prompt 514) already returns for it to decide whether it is safe to
# describe. This is the last link in the existing chain -
#
#   snapshot (508) -> comparison (509) -> comparison validation (510) ->
#   trend summary (511) -> trend validation (512) -> unified report
#   (513) -> unified report validation (514) -> human-readable summary
#   (515, this function)
#
# and follows the exact "judge first, describe second" shape
# `build_learned_knowledge_analysis_summary()` (Prompt 507) already uses
# for the Prompt 505/506 pair: when the given validation says the report
# is not fully valid, this NEVER inspects the report's individual
# sections, never guesses or repairs a value, and never proceeds as
# though the report were trustworthy - it only ever states that the
# report is invalid and carries the validation's own errors forward
# unchanged. Nothing here is a second report/validation/trend/analytics
# system: every value in a valid summary is a straight readout of a
# field `build_learned_knowledge_diagnostic_report()` already computed,
# further gated by the report's own per-section `"available"` flags and
# by re-checking the embedded `comparison_validation`/`trend_validation`
# results already inside it - nothing is recomputed, re-derived, scored,
# ranked, or interpreted as a cause or a prediction.

REPORT_VALIDITY_VALID = "valid"
REPORT_VALIDITY_INVALID = "invalid"

# Fixed section order, reused for `available_sections`/`unavailable_sections`
# and for the `"metrics"` dict, so every summary presents information in
# the same order regardless of which sections happen to be available.
_SUMMARY_SECTIONS = (
    "evaluation_counts",
    "rates",
    "dominant_rejection_reason",
    "comparison_changes",
    "trend",
    "validation_statuses",
)

# Plain-English rewording of the exact Prompt 509/511 categorical change
# states, for readability only - never a reinterpretation of what they
# mean. "insufficient data" covers both Prompt 509's "not_comparable"
# (two snapshots that could not be compared) and Prompt 511's
# "insufficient_data" (no eligible comparisons) - both already mean
# "nothing usable to compare here", just at different levels.
_CATEGORICAL_CHANGE_TEXT = {
    CHANGE_UNCHANGED: "unchanged",
    CHANGE_CHANGED: "changed",
    CHANGE_BECAME_AVAILABLE: "appeared",
    CHANGE_BECAME_EMPTY: "disappeared",
    CHANGE_NOT_COMPARABLE: "insufficient data",
    TREND_INSUFFICIENT_DATA: "insufficient data",
}

# Plain-English rewording of the exact Prompt 511 numeric trend states -
# already exactly the vocabulary required, spelled out for clarity.
_TREND_STATE_TEXT = {
    TREND_INCREASED: "increased",
    TREND_DECREASED: "decreased",
    CHANGE_UNCHANGED: "unchanged",
    TREND_INSUFFICIENT_DATA: "insufficient data",
}


def _descriptive_change(state):
    """The readable text for a Prompt 509/511 categorical change state,
    or `state` itself unchanged when it is not one of the recognized
    values (never raises, never fabricates a state that was not
    there)."""
    return _CATEGORICAL_CHANGE_TEXT.get(state, state)


def _descriptive_trend(state):
    """The readable text for a Prompt 511 numeric trend state, or
    `state` itself unchanged when unrecognized."""
    return _TREND_STATE_TEXT.get(state, state)


def _format_rate_text(rate):
    """A rate (a `0.0`-`1.0` float already computed elsewhere) shown as
    a percentage purely for display - e.g. `"60.0%"`. Never used as the
    stored metric value itself (that stays the exact, unrounded
    number); `None` is shown as `"n/a"` rather than `"0.0%"`, so a
    genuinely missing rate is never mistaken for a zero one."""
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        return "n/a"
    return "{0:.1%}".format(rate)


def _invalid_report_summary(errors):
    return {
        "summary_text": "Diagnostic report is INVALID. Validation errors: " + _errors_text(errors),
        "report_validity": REPORT_VALIDITY_INVALID,
        "validation_errors": list(errors),
        "available_sections": [],
        "unavailable_sections": list(_SUMMARY_SECTIONS),
        "metrics": {section: None for section in _SUMMARY_SECTIONS},
    }


def _summary_comparison_metrics(latest_comparison):
    return {
        "earlier": copy.deepcopy(latest_comparison.get("earlier")),
        "later": copy.deepcopy(latest_comparison.get("later")),
        "comparable": latest_comparison.get("comparable"),
        "identical": latest_comparison.get("identical"),
        "changed_fields": list(latest_comparison.get("changed_fields", [])),
        "numeric": copy.deepcopy(latest_comparison.get("numeric", {})),
        "dominant_rejection_reason_change": _descriptive_change(
            latest_comparison.get("dominant_rejection_reason", {}).get("change")),
        "validation_status_change": _descriptive_change(
            latest_comparison.get("validation_status", {}).get("change")),
    }


def _summary_comparison_text(latest_comparison):
    if latest_comparison.get("comparable") is False:
        return ("Comparison: the two most recent snapshots were not comparable "
                "(one or both failed their own validation).")
    if latest_comparison.get("identical"):
        return "Comparison: no change since the previous comparable snapshot."

    numeric = latest_comparison.get("numeric", {})
    reason_change = latest_comparison.get("dominant_rejection_reason", {})
    status_change = latest_comparison.get("validation_status", {})
    field_texts = []
    for field in latest_comparison.get("changed_fields", []):
        if field in numeric:
            entry = numeric[field]
            field_texts.append("{0}: {1} -> {2} (delta {3})".format(
                field, entry.get("earlier"), entry.get("later"), entry.get("delta")))
        elif field == "dominant_rejection_reason":
            field_texts.append("dominant_rejection_reason: {0} -> {1} ({2})".format(
                reason_change.get("earlier"), reason_change.get("later"),
                _descriptive_change(reason_change.get("change"))))
        elif field == "validation_status":
            field_texts.append("validation_status: {0} -> {1} ({2})".format(
                status_change.get("earlier"), status_change.get("later"),
                _descriptive_change(status_change.get("change"))))
    return "Comparison changes: " + "; ".join(field_texts) + "."


def _summary_trend_metrics(trend_summary):
    trend_metrics = {"source": None}
    for field, entry in trend_summary.get("numeric", {}).items():
        trend_metrics[field] = {
            "state": _descriptive_trend(entry.get("state")),
            "start": entry.get("start"),
            "end": entry.get("end"),
            "delta": entry.get("delta"),
        }
    dom_trend = trend_summary.get("dominant_rejection_reason", {})
    trend_metrics["dominant_rejection_reason"] = {
        "state": _descriptive_change(dom_trend.get("state")),
        "start": dom_trend.get("start"),
        "end": dom_trend.get("end"),
    }
    status_trend = trend_summary.get("validation_status", {})
    trend_metrics["validation_status"] = {
        "state": _descriptive_change(status_trend.get("state")),
        "start": status_trend.get("start"),
        "end": status_trend.get("end"),
    }
    trend_metrics["chronological_range"] = copy.deepcopy(trend_summary.get("chronological_range"))
    trend_metrics["eligible_count"] = trend_summary.get("eligible_count")
    trend_metrics["total_comparisons"] = trend_summary.get("total_comparisons")
    return trend_metrics


def _summary_trend_text(trend_summary, trend_metrics, source):
    field_texts = [
        "{0}: {1}".format(field, trend_metrics[field]["state"])
        for field in trend_summary.get("numeric", {})
    ]
    field_texts.append(
        "dominant_rejection_reason: {0}".format(trend_metrics["dominant_rejection_reason"]["state"]))
    field_texts.append(
        "validation_status: {0}".format(trend_metrics["validation_status"]["state"]))
    return "Trend (source: {0}; {1} of {2} comparisons eligible): {3}.".format(
        source, trend_summary.get("eligible_count"), trend_summary.get("total_comparisons"),
        "; ".join(field_texts))


def format_learned_knowledge_diagnostic_summary(report, validation):
    """Build a plain dict, human-readable presentation of `report` (a
    Prompt 513 `build_learned_knowledge_diagnostic_report()` result)
    using its own already-computed `validation` (a Prompt 514
    `validate_learned_knowledge_diagnostic_report(report, ...)` result)
    to decide whether it is safe to describe - the same "judge first,
    describe second" shape `build_learned_knowledge_analysis_summary()`
    (Prompt 507) already uses for the Prompt 505/506 pair.

    When `validation["valid"]` is not `True` (or `validation` is not a
    recognizable Prompt 514 result, or `report` itself is not a dict),
    this NEVER inspects `report`'s individual sections, never guesses
    or repairs a value, and never proceeds as though `report` were
    valid. It returns exactly:

        {
            "summary_text": "<short statement that the report is
                              invalid, listing the validation errors>",
            "report_validity": "invalid",
            "validation_errors": [<validation's own "errors", unchanged>],
            "available_sections": [],
            "unavailable_sections": [<every summary section - see
                                       `_SUMMARY_SECTIONS`>],
            "metrics": {<every summary section key>: None, ...},
        }

    When `validation["valid"]` is `True`, returns:

        {
            "summary_text": "<concise, deterministic, multi-sentence
                              human-readable summary>",
            "report_validity": "valid",
            "validation_errors": [],
            "available_sections": [<section names actually described>],
            "unavailable_sections": [<the rest>],
            "metrics": {<every section key>: <dict, str/None, or None>},
        }

    Every summary section is read straight off `report`'s own already-
    computed, already-judged fields - nothing here re-derives a count,
    re-runs a comparison or trend summarizer, or reinterprets a
    validation result:

        "evaluation_counts" / "rates" / "dominant_rejection_reason" -
            from `report["snapshots"]["latest"]`, available exactly
            when a latest snapshot exists AND its own
            `validation_status` is `"valid"` (an invalid snapshot's
            analysis fields are `None` - see Prompt 508 - so nothing
            is ever read out of one);
        "comparison_changes" - from `report["comparison"]["latest"]`,
            available exactly when a latest comparison exists, its own
            `"valid"` is `True` (both snapshots it compares were
            structurally well-formed), and
            `report["comparison_validation"]["result"]["valid"]` is
            `True` (the comparison is a trustworthy, well-formed
            Prompt 510 result). A comparable-but-non-comparable result
            (`"comparable": False` - one snapshot's own analysis was
            invalid) is still described, but only as such, never with
            fabricated numeric deltas;
        "trend" - from `report["trend"]["summary"]`, available exactly
            when a trend summary exists and
            `report["trend_validation"]["result"]["valid"]` is `True`;
        "validation_statuses" - always available; a plain readout of
            `report["structural_status"]` plus whichever of the latest
            snapshot's/comparison's/trend's own validation outcomes the
            report carries (`None` for one not carried).

    Trend/categorical states are presented with a plain-English
    rewording of the exact vocabulary Prompt 509/511 already use
    (`"increased"`, `"decreased"`, `"unchanged"`, `"insufficient data"`
    for numeric trends; `"unchanged"`, `"changed"`, `"appeared"`,
    `"disappeared"`, `"insufficient data"` for categorical ones - a
    readability-only rewording of Prompt 509's `"became_available"`/
    `"became_empty"`/`"not_comparable"`, never a reinterpretation of
    what they mean). Rates are additionally shown as a percentage in
    `summary_text` purely for display (e.g. `"60.0%"`); every value
    inside `"metrics"` is the exact, unrounded number `report` already
    carries. Nothing here infers a cause, predicts a future value, or
    produces a recommendation, and nothing is described as good/bad/
    healthy/unhealthy/successful/unsuccessful - the only status words
    used (`"valid"`/`"invalid"`/`"no_data"`/`"partial"`, and the
    trend/change words above) are literal source values or their
    direct, fixed, readability-only rewording, never a new judgement.

    Deterministic: the same `report` and `validation` always produce an
    equal summary dict, with sections in the same fixed order. Never
    mutates `report` or `validation`, or anything inside them (every
    embedded structure is read via `.get()` or copied out with
    `copy.deepcopy`); never touches a snapshot history, statistics
    object, trace, or learned record; is not wired into the gate/
    decision/response path; and is not exposed to normal user-facing
    responses (same internal-only, diagnostic-only posture as Prompt
    504-514).
    """
    if not isinstance(validation, dict) or "valid" not in validation:
        errors = (
            list(validation.get("errors", []))
            if isinstance(validation, dict) else ["validation_not_a_dict"]
        )
        return _invalid_report_summary(errors)

    if not validation.get("valid", False):
        return _invalid_report_summary(list(validation.get("errors", [])))

    if not isinstance(report, dict):
        return _invalid_report_summary(["report_not_a_dict"])

    snapshots_section = report.get("snapshots") or {}
    comparison_section = report.get("comparison") or {}
    comparison_validation_section = report.get("comparison_validation") or {}
    trend_section = report.get("trend") or {}
    trend_validation_section = report.get("trend_validation") or {}
    structural_status = report.get("structural_status")

    latest_snapshot = snapshots_section.get("latest")
    evaluation_available = (
        snapshots_section.get("available") is True
        and isinstance(latest_snapshot, dict)
        and latest_snapshot.get("validation_status") == SNAPSHOT_VALIDATION_VALID
    )

    latest_comparison = comparison_section.get("latest")
    comparison_validation_result = comparison_validation_section.get("result")
    comparison_available = (
        comparison_section.get("available") is True
        and isinstance(latest_comparison, dict)
        and latest_comparison.get("valid") is True
        and isinstance(comparison_validation_result, dict)
        and comparison_validation_result.get("valid") is True
    )

    trend_summary = trend_section.get("summary")
    trend_validation_result = trend_validation_section.get("result")
    trend_available = (
        trend_section.get("available") is True
        and isinstance(trend_summary, dict)
        and isinstance(trend_validation_result, dict)
        and trend_validation_result.get("valid") is True
    )

    metrics = {}
    available_sections = []
    unavailable_sections = []
    lines = ["Diagnostic report status: {0}.".format(structural_status)]

    if evaluation_available:
        metrics["evaluation_counts"] = {
            "total_evaluations": latest_snapshot["total_evaluations"],
            "accepted_count": latest_snapshot["accepted_count"],
            "rejected_count": latest_snapshot["rejected_count"],
            "no_candidate_count": latest_snapshot["no_candidate_count"],
        }
        metrics["rates"] = {
            "acceptance_rate": latest_snapshot["acceptance_rate"],
            "rejection_rate": latest_snapshot["rejection_rate"],
        }
        metrics["dominant_rejection_reason"] = latest_snapshot["dominant_rejection_reason"]
        available_sections.extend(["evaluation_counts", "rates", "dominant_rejection_reason"])

        lines.append(
            "Evaluations: {total} total - {accepted} accepted ({acc_pct}), "
            "{rejected} rejected ({rej_pct}), {no_candidate} with no candidate.".format(
                total=latest_snapshot["total_evaluations"],
                accepted=latest_snapshot["accepted_count"],
                acc_pct=_format_rate_text(latest_snapshot["acceptance_rate"]),
                rejected=latest_snapshot["rejected_count"],
                rej_pct=_format_rate_text(latest_snapshot["rejection_rate"]),
                no_candidate=latest_snapshot["no_candidate_count"],
            )
        )
        dominant = latest_snapshot["dominant_rejection_reason"]
        if dominant is not None:
            lines.append("Dominant rejection reason: {0}.".format(dominant))
        else:
            lines.append("No dominant rejection reason (no rejected decisions).")
    else:
        metrics["evaluation_counts"] = None
        metrics["rates"] = None
        metrics["dominant_rejection_reason"] = None
        unavailable_sections.extend(["evaluation_counts", "rates", "dominant_rejection_reason"])
        lines.append("Evaluation counts, rates and dominant rejection reason: unavailable.")

    if comparison_available:
        metrics["comparison_changes"] = _summary_comparison_metrics(latest_comparison)
        available_sections.append("comparison_changes")
        lines.append(_summary_comparison_text(latest_comparison))
    else:
        metrics["comparison_changes"] = None
        unavailable_sections.append("comparison_changes")
        lines.append("Comparison changes: unavailable.")

    if trend_available:
        trend_metrics = _summary_trend_metrics(trend_summary)
        trend_metrics["source"] = trend_section.get("source")
        metrics["trend"] = trend_metrics
        available_sections.append("trend")
        lines.append(_summary_trend_text(trend_summary, trend_metrics, trend_section.get("source")))
    else:
        metrics["trend"] = None
        unavailable_sections.append("trend")
        lines.append("Trend: unavailable.")

    validation_statuses = {
        "structural_status": structural_status,
        "latest_snapshot_validation_status": (
            latest_snapshot.get("validation_status") if isinstance(latest_snapshot, dict) else None
        ),
        "comparison_validation": (
            comparison_validation_result.get("valid")
            if isinstance(comparison_validation_result, dict) else None
        ),
        "trend_validation": (
            trend_validation_result.get("valid")
            if isinstance(trend_validation_result, dict) else None
        ),
    }
    metrics["validation_statuses"] = validation_statuses
    available_sections.append("validation_statuses")
    lines.append(
        "Validation statuses: structural_status={0}, latest_snapshot={1}, "
        "comparison_validation={2}, trend_validation={3}.".format(
            validation_statuses["structural_status"],
            validation_statuses["latest_snapshot_validation_status"],
            validation_statuses["comparison_validation"],
            validation_statuses["trend_validation"],
        )
    )

    return {
        "summary_text": " ".join(lines),
        "report_validity": REPORT_VALIDITY_VALID,
        "validation_errors": [],
        "available_sections": available_sections,
        "unavailable_sections": unavailable_sections,
        "metrics": metrics,
    }


# ----------------------------------------------------------------------
# Prompt 516 - section selection over a Prompt 515 human-readable
# diagnostic summary
# ----------------------------------------------------------------------
# A thin, deterministic, READ-ONLY selection layer over the dict
# `format_learned_knowledge_diagnostic_summary()` (Prompt 515) returns.
# It is the last link in the existing chain -
#
#   snapshot (508) -> comparison (509) -> comparison validation (510) ->
#   trend summary (511) -> trend validation (512) -> unified report
#   (513) -> unified report validation (514) -> human-readable summary
#   (515) -> section filtering (516, this function)
#
# It reuses Prompt 515's own section vocabulary (`_SUMMARY_SECTIONS`),
# its `"available_sections"` / `"metrics"` / `"report_validity"` /
# `"validation_errors"` fields, and its readability helpers
# (`_format_rate_text`, `_errors_text`). It only ever chooses which
# already-existing sections of a summary to expose; it computes no new
# metric, score, ranking, prediction, cause, or recommendation, never
# repairs or re-judges the summary it is given, and never invents a
# section that is not there.

# Every metric key inside a Prompt 515 trend section that is NOT itself a
# per-field `{"state", ...}` entry.
_FILTER_TREND_NON_FIELD_KEYS = (
    "source", "chronological_range", "eligible_count", "total_comparisons",
)


def _filter_name_text(name):
    """A section name as shown in text: a string as-is, anything else via
    `repr()` (so a non-string request is reported, never crashes)."""
    return name if isinstance(name, str) else repr(name)


def _filter_names_text(names):
    return ", ".join(_filter_name_text(name) for name in names)


def _filter_request_items(requested_sections):
    """The requested section names as a plain list, in a deterministic
    order. `None` means nothing was requested (never "everything"); a
    bare string is one name; a set/frozenset (whose own iteration order
    is not stable across processes) is ordered by `repr()`; any other
    iterable keeps its own order; a non-iterable is a single (unknown)
    name."""
    if requested_sections is None:
        return []
    if isinstance(requested_sections, str):
        return [requested_sections]
    if isinstance(requested_sections, (set, frozenset)):
        return sorted(requested_sections, key=repr)
    try:
        return list(requested_sections)
    except TypeError:
        return [requested_sections]


def _filter_dedupe(items):
    """`items` without repeats, first occurrence kept, order preserved.
    Two names repeat only when they have the same type and are equal, so
    `1`, `1.0` and `True` are never merged. Works for unhashable items."""
    seen = []
    result = []
    for item in items:
        if any(type(other) is type(item) and other == item for other in seen):
            continue
        seen.append(item)
        result.append(item)
    return result


def _filter_source_status(summary):
    """(`report_validity`, `validation_errors`) to report for `summary`.

    A well-formed Prompt 515 summary keeps exactly the validity and the
    errors it already carries. A summary that is not a Prompt 515 dict,
    is missing/mistyping a field this layer must read, or claims to be
    valid while carrying errors is reported as invalid (it is never
    repaired or reinterpreted as valid)."""
    if not isinstance(summary, dict):
        return REPORT_VALIDITY_INVALID, ["summary_not_a_dict"]

    source_errors = summary.get("validation_errors")
    carried_errors = copy.deepcopy(source_errors) if isinstance(source_errors, list) else []
    validity = summary.get("report_validity")

    if validity == REPORT_VALIDITY_INVALID:
        return REPORT_VALIDITY_INVALID, carried_errors
    if validity != REPORT_VALIDITY_VALID:
        return REPORT_VALIDITY_INVALID, carried_errors + ["summary_report_validity_unrecognized"]

    malformed = [
        "summary_field_missing_or_malformed:" + field
        for field, expected in (
            ("validation_errors", list), ("available_sections", list),
            ("unavailable_sections", list), ("metrics", dict),
        )
        if not isinstance(summary.get(field), expected)
    ]
    if malformed:
        return REPORT_VALIDITY_INVALID, carried_errors + malformed
    if carried_errors:
        return REPORT_VALIDITY_INVALID, carried_errors + ["summary_valid_with_validation_errors"]
    return REPORT_VALIDITY_VALID, []


def _filter_evaluation_counts_text(counts):
    return "Evaluation counts: {0} total, {1} accepted, {2} rejected, {3} with no candidate.".format(
        counts.get("total_evaluations"), counts.get("accepted_count"),
        counts.get("rejected_count"), counts.get("no_candidate_count"))


def _filter_rates_text(rates):
    return "Rates: acceptance rate {0}, rejection rate {1}.".format(
        _format_rate_text(rates.get("acceptance_rate")), _format_rate_text(rates.get("rejection_rate")))


def _filter_dominant_text(dominant):
    if dominant is not None:
        return "Dominant rejection reason: {0}.".format(dominant)
    return "No dominant rejection reason (no rejected decisions)."


def _filter_comparison_text(comparison):
    if comparison.get("comparable") is False:
        return ("Comparison: the two most recent snapshots were not comparable "
                "(one or both failed their own validation).")
    if comparison.get("identical"):
        return "Comparison: no change since the previous comparable snapshot."
    numeric = comparison.get("numeric", {})
    field_texts = []
    for field in comparison.get("changed_fields", []):
        if field in numeric:
            entry = numeric[field]
            field_texts.append("{0}: {1} -> {2} (delta {3})".format(
                field, entry.get("earlier"), entry.get("later"), entry.get("delta")))
        elif field == "dominant_rejection_reason":
            field_texts.append("dominant_rejection_reason: {0}".format(
                comparison.get("dominant_rejection_reason_change")))
        elif field == "validation_status":
            field_texts.append("validation_status: {0}".format(
                comparison.get("validation_status_change")))
    return "Comparison changes: " + "; ".join(field_texts) + "."


def _filter_trend_text(trend):
    field_texts = [
        "{0}: {1}".format(field, entry.get("state"))
        for field, entry in trend.items()
        if field not in _FILTER_TREND_NON_FIELD_KEYS and isinstance(entry, dict) and "state" in entry
    ]
    return "Trend (source: {0}; {1} of {2} comparisons eligible): {3}.".format(
        trend.get("source"), trend.get("eligible_count"), trend.get("total_comparisons"),
        "; ".join(field_texts))


def _filter_validation_statuses_text(statuses):
    return (
        "Validation statuses: structural_status={0}, latest_snapshot={1}, "
        "comparison_validation={2}, trend_validation={3}.".format(
            statuses.get("structural_status"), statuses.get("latest_snapshot_validation_status"),
            statuses.get("comparison_validation"), statuses.get("trend_validation"))
    )


_FILTER_SECTION_TEXT = {
    "evaluation_counts": _filter_evaluation_counts_text,
    "rates": _filter_rates_text,
    "dominant_rejection_reason": _filter_dominant_text,
    "comparison_changes": _filter_comparison_text,
    "trend": _filter_trend_text,
    "validation_statuses": _filter_validation_statuses_text,
}


def _filter_section_text(section, value):
    """One readable line for an already-selected section's copied value.
    Falls back to a plain `section: value` readout if the value is not
    the shape Prompt 515 produces - never raises, never invents data."""
    try:
        return _FILTER_SECTION_TEXT[section](value)
    except (AttributeError, TypeError, KeyError):
        return "{0}: {1}".format(section, value)


def filter_learned_knowledge_diagnostic_summary(summary, requested_sections=None):
    """Return only the requested, already-existing sections of `summary`
    (a Prompt 515 `format_learned_knowledge_diagnostic_summary()` result)
    as a plain dict:

        {
            "requested_sections": [<requested names, repeats removed,
                                     first-request order>],
            "included_sections": [<requested sections present in the
                                     summary, in the fixed Prompt 515
                                     section order>],
            "unavailable_sections": [<requested sections that are real
                                     summary sections but not available
                                     in this summary, in the same fixed
                                     order>],
            "unknown_sections": [<requested names that are not summary
                                     sections at all, first-request
                                     order>],
            "summary_text": "<deterministic text for the included
                              sections only>",
            "report_validity": "valid" | "invalid",
            "validation_errors": [<the summary's own errors, unchanged>],
            "metrics": {<included section>: <that section's value,
                          copied exactly>, <unavailable section>: None},
        }

    Section names are exactly the Prompt 515 ones (`"evaluation_counts"`,
    `"rates"`, `"dominant_rejection_reason"`, `"comparison_changes"`,
    `"trend"`, `"validation_statuses"`); matching is exact and
    case-sensitive - no fuzzy matching, guessing, or renaming. A section
    is *included* only when the summary is valid, lists it in its own
    `"available_sections"`, and carries its value in `"metrics"`. A
    real section the summary does not offer is *unavailable*: it is
    named as such and its `"metrics"` entry is `None`; nothing is ever
    generated in its place. A name that is not a summary section is
    *unknown* and appears only in `"unknown_sections"`. `None` or an
    empty request selects nothing (it never means "everything"); to get
    every available section, pass `summary["available_sections"]`.

    When `summary` is not a valid Prompt 515 summary, nothing is
    included: `"report_validity"` is `"invalid"`, the summary's own
    `"validation_errors"` are carried forward unchanged, every
    requested real section is `"unavailable"`, and `"summary_text"`
    says the summary is invalid. The summary is never repaired, and
    invalid data is never presented as valid.

    Included values are deep copies of what the summary carries - exact
    numbers (type and precision), Prompt 511/515 trend states
    (`"increased"`, `"decreased"`, `"unchanged"`, `"insufficient
    data"`), categorical states (`"unchanged"`, `"changed"`,
    `"appeared"`, `"disappeared"`, `"insufficient data"`) and
    chronological fields are not recomputed, reworded, reordered, or
    rounded. Nothing here scores, ranks, judges the importance of,
    predicts from, or recommends anything.

    Deterministic: the same `summary` and `requested_sections` always
    produce an equal result. Never mutates `summary` or anything inside
    it, and never touches a snapshot, comparison, trend summary,
    validation result, report, learned record, memory, or application
    state; is not wired into the gate/decision/response path; and is not
    exposed to normal user-facing responses (same internal-only,
    diagnostic-only posture as Prompts 504-515).
    """
    requested = _filter_dedupe(_filter_request_items(requested_sections))
    validity, errors = _filter_source_status(summary)
    valid = validity == REPORT_VALIDITY_VALID

    known = [section for section in _SUMMARY_SECTIONS if section in requested]
    unknown = [name for name in requested if not (isinstance(name, str) and name in _SUMMARY_SECTIONS)]

    if valid:
        offered = summary["available_sections"]
        source_metrics = summary["metrics"]
        included = [s for s in known if s in offered and s in source_metrics]
    else:
        source_metrics = {}
        included = []
    unavailable = [section for section in known if section not in included]

    metrics = {}
    for section in known:
        metrics[section] = copy.deepcopy(source_metrics[section]) if section in included else None

    if not valid:
        lines = ["Diagnostic summary is INVALID. Validation errors: "
                 + _errors_text([str(error) for error in errors])]
    elif not requested:
        lines = ["No diagnostic summary sections were requested."]
    else:
        lines = [_filter_section_text(section, metrics[section]) for section in included]
    if unavailable:
        lines.append("Unavailable sections: {0}.".format(_filter_names_text(unavailable)))
    if unknown:
        lines.append("Unknown sections: {0}.".format(_filter_names_text(unknown)))

    return {
        "requested_sections": copy.deepcopy(requested),
        "included_sections": included,
        "unavailable_sections": unavailable,
        "unknown_sections": copy.deepcopy(unknown),
        "summary_text": " ".join(lines),
        "report_validity": validity,
        "validation_errors": errors,
        "metrics": metrics,
    }


# ----------------------------------------------------------------------
# Prompt 517 - bounded snapshots of a Prompt 516 filtered diagnostic
# summary
# ----------------------------------------------------------------------
# A small, diagnostic-only, in-memory record of point-in-time snapshots
# of what `filter_learned_knowledge_diagnostic_summary()` (Prompt 516)
# returned, so a future component can inspect - or compare - which
# diagnostic sections were selected, and what they held, at different
# moments. It is the last link in the existing chain -
#
#   snapshot (508) -> comparison (509) -> comparison validation (510) ->
#   trend summary (511) -> trend validation (512) -> unified report
#   (513) -> unified report validation (514) -> human-readable summary
#   (515) -> section filtering (516) -> filtered-summary snapshot (517)
#
# Architecture reuse: this is NOT a second history system. It uses the
# exact storage the Prompt 508 history uses (`_BoundedDiagnosticSnapshotStore`:
# the same bounded FIFO retention/`DEFAULT_MAX_SNAPSHOT_HISTORY`, the same
# never-reused 1-based `sequence`, the same `snapshot_id` format, the same
# `get_all`/`get_latest`/`get_recent`, deep-copy in and out) - that
# storage was moved out of the Prompt 508 class, unchanged, so both
# histories share one implementation instead of two.
#
# It is a separate class from `LearnedKnowledgeDiagnosticSnapshotHistory`
# on purpose: Prompt 508 snapshots have a fixed analysis-field shape that
# the Prompt 509-514 comparison/trend/report code reads, so filtered-
# summary snapshots must never be mixed into (or be mistaken for) that
# history. Each snapshot carries `"snapshot_kind": "filtered_summary"`
# so its identity is unambiguous even though the id format is shared.
#
# A snapshot is built ONLY from the fields of a Prompt 516 result that
# describe diagnostic sections: raw section names the caller typed that
# are not real sections are stored as a count, never as text; only the
# known keys of each section are kept; and nothing outside the filtered
# summary (no report, learned record, trace, conversation, user content,
# or application state) is read. Nothing here reads a snapshot back to
# make a decision, scores or ranks anything, or is wired into the gate/
# decision/response path.

SNAPSHOT_KIND_FILTERED_SUMMARY = "filtered_summary"
_FILTERED_SNAPSHOT_SOURCE = "filtered_diagnostic_summary"

# The keys a Prompt 515/516 section value may carry, by section. Anything
# else found inside a section is dropped, never stored. (The
# `dominant_rejection_reason` section is a bare `str`/`None`, not a dict.)
_FILTERED_SNAPSHOT_SECTION_KEYS = {
    "evaluation_counts": (
        "total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
    ),
    "rates": ("acceptance_rate", "rejection_rate"),
    "comparison_changes": (
        "earlier", "later", "comparable", "identical", "changed_fields", "numeric",
        "dominant_rejection_reason_change", "validation_status_change",
    ),
    "trend": (
        ("source",) + tuple(_TREND_NUMERIC_FIELDS)
        + ("dominant_rejection_reason", "validation_status", "chronological_range",
           "eligible_count", "total_comparisons")
    ),
    "validation_statuses": (
        "structural_status", "latest_snapshot_validation_status",
        "comparison_validation", "trend_validation",
    ),
}


def _filtered_snapshot_section_shape_ok(section, value):
    if section == "dominant_rejection_reason":
        return value is None or isinstance(value, str)
    return isinstance(value, dict)


def _filtered_snapshot_section_copy(section, value):
    """A deep copy of `value` keeping only the keys its section is known
    to carry, in the source's own order."""
    if section == "dominant_rejection_reason":
        return value
    allowed = _FILTERED_SNAPSHOT_SECTION_KEYS[section]
    return {key: copy.deepcopy(item) for key, item in value.items() if key in allowed}


def _filtered_snapshot_problems(filtered_summary):
    """Why `filtered_summary` is not a well-formed Prompt 516 result
    (`[]` when it is). Never repairs anything."""
    if not isinstance(filtered_summary, dict):
        return ["filtered_summary_not_a_dict"]
    problems = [
        "filtered_summary_field_missing_or_malformed:" + field
        for field, expected in (
            ("included_sections", list), ("unavailable_sections", list),
            ("unknown_sections", list), ("validation_errors", list), ("metrics", dict),
        )
        if not isinstance(filtered_summary.get(field), expected)
    ]
    validity = filtered_summary.get("report_validity")
    if validity not in (REPORT_VALIDITY_VALID, REPORT_VALIDITY_INVALID):
        problems.append("filtered_summary_report_validity_unrecognized")
    if problems:
        return problems

    included = filtered_summary["included_sections"]
    unavailable = filtered_summary["unavailable_sections"]
    metrics = filtered_summary["metrics"]
    names = included + unavailable
    if (any(not isinstance(name, str) or name not in _SUMMARY_SECTIONS for name in names)
            or len(set(names)) != len(names)):
        return ["filtered_summary_section_names_malformed"]

    for name in included:
        if name not in metrics or not _filtered_snapshot_section_shape_ok(name, metrics[name]):
            problems.append("filtered_summary_section_malformed:" + name)
    for name in unavailable:
        if metrics.get(name) is not None:
            problems.append("filtered_summary_section_malformed:" + name)
    if validity == REPORT_VALIDITY_VALID and filtered_summary["validation_errors"]:
        problems.append("filtered_summary_valid_with_validation_errors")
    if validity == REPORT_VALIDITY_INVALID and included:
        problems.append("filtered_summary_invalid_with_included_sections")
    return problems


def _filtered_snapshot_errors(filtered_summary):
    """The filtered summary's own `validation_errors` as plain strings
    (or `[]` when it has none it can be trusted to carry)."""
    if not isinstance(filtered_summary, dict):
        return []
    errors = filtered_summary.get("validation_errors")
    if not isinstance(errors, list):
        return []
    return [error if isinstance(error, str) else str(error) for error in errors]


def _build_filtered_summary_snapshot(filtered_summary, sequence):
    problems = _filtered_snapshot_problems(filtered_summary)
    snapshot = {
        "snapshot_id": _SNAPSHOT_ID_FORMAT % sequence,
        "sequence": sequence,
        "snapshot_kind": SNAPSHOT_KIND_FILTERED_SUMMARY,
        "creation_context": {"source": _FILTERED_SNAPSHOT_SOURCE},
    }
    if problems:
        # Not a well-formed Prompt 516 result: nothing in it is trusted
        # or stored beyond the errors it already carried plus why it was
        # rejected here.
        snapshot.update({
            "validation_status": SNAPSHOT_VALIDATION_INVALID,
            "validation_errors": _filtered_snapshot_errors(filtered_summary) + problems,
            "included_sections": [],
            "unavailable_sections": [],
            "unknown_section_count": None,
            "metrics": {},
        })
        return snapshot

    included = list(filtered_summary["included_sections"])
    unavailable = list(filtered_summary["unavailable_sections"])
    source_metrics = filtered_summary["metrics"]
    metrics = {}
    for section in _SUMMARY_SECTIONS:
        if section in included:
            metrics[section] = _filtered_snapshot_section_copy(section, source_metrics[section])
        elif section in unavailable:
            metrics[section] = None
    snapshot.update({
        "validation_status": (
            SNAPSHOT_VALIDATION_VALID
            if filtered_summary["report_validity"] == REPORT_VALIDITY_VALID
            else SNAPSHOT_VALIDATION_INVALID
        ),
        "validation_errors": _filtered_snapshot_errors(filtered_summary),
        "included_sections": included,
        "unavailable_sections": unavailable,
        "unknown_section_count": len(filtered_summary["unknown_sections"]),
        "metrics": metrics,
    })
    return snapshot


class LearnedKnowledgeFilteredSummarySnapshotHistory(_BoundedDiagnosticSnapshotStore):
    """Bounded, in-memory, oldest-first history of Prompt 516 filtered
    diagnostic summaries, sharing the Prompt 508 storage (see the block
    comment above). A snapshot is a plain dict, always with exactly
    these keys:

        {
            "snapshot_id": "learned_knowledge_snapshot_000001",
            "sequence": 1,                     # 1-based, increasing, never reused
            "snapshot_kind": "filtered_summary",
            "creation_context": {"source": "filtered_diagnostic_summary"},
            "validation_status": "valid" | "invalid",
            "validation_errors": [<str>, ...], # the summary's own errors, unchanged
            "included_sections": [<section name>, ...],
            "unavailable_sections": [<section name>, ...],
            "unknown_section_count": <int or None>,
            "metrics": {<section>: <that section's value, exact> | None, ...},
        }

    `included_sections` / `unavailable_sections` are the Prompt 515
    section names the filtered summary selected; `metrics` holds an
    included section's exact value (numbers, rates, trend and categorical
    states, chronological fields - as the filtered summary carried them)
    or `None` for an unavailable one, in the fixed Prompt 515 section
    order. `unknown_section_count` is only how many requested names were
    not real sections - the names themselves are never stored (`None`
    when the summary was too malformed to say).

    A filtered summary that is itself invalid stays invalid
    (`validation_status` `"invalid"`, its own errors kept, its requested
    sections shown as unavailable). Anything that is not a well-formed
    Prompt 516 result becomes an `"invalid"` snapshot with no sections,
    the errors it carried, and a reason; it is never repaired or
    presented as valid, and `record_filtered_summary()` never raises for
    it. No timestamps, raw user text, conversation, trace, learned
    record, or report is stored, so a snapshot is a pure function of the
    filtered summary and the sequence number.

    Isolation, capacity, `get_all()`, `get_latest()`, `get_recent()`,
    and `len()` are exactly Prompt 508's. `get_by_sequence()` returns a
    copy of the held snapshot with that sequence (or `None`).

    The Prompt 508 analysis-snapshot operations do not apply to this
    history, so `record()`, `record_statistics()`, `compare_sequences()`
    and `compare_latest()` raise `NotImplementedError` rather than mixing
    two kinds of snapshot.
    """

    def record_filtered_summary(self, filtered_summary):
        """Store a snapshot of `filtered_summary` (a Prompt 516
        `filter_learned_knowledge_diagnostic_summary()` result) and
        return a copy of what was stored. Never mutates
        `filtered_summary`, and nothing in the stored snapshot shares
        state with it."""
        snapshot = _build_filtered_summary_snapshot(filtered_summary, self._next_sequence)
        return self._store_snapshot(snapshot)

    def get_by_sequence(self, sequence):
        """A fresh copy of the held snapshot whose `sequence` is
        `sequence`, or `None` (unknown, evicted, non-int)."""
        return self._copy_of_sequence(sequence)

    def _unsupported(self, name):
        raise NotImplementedError(
            "{0}() is a Prompt 508 analysis-snapshot operation and is not supported by "
            "LearnedKnowledgeFilteredSummarySnapshotHistory".format(name))

    def record(self, *args, **kwargs):
        self._unsupported("record")

    def record_statistics(self, *args, **kwargs):
        self._unsupported("record_statistics")

    def compare_sequences(self, *args, **kwargs):
        self._unsupported("compare_sequences")

    def compare_latest(self, *args, **kwargs):
        self._unsupported("compare_latest")


# ----------------------------------------------------------------------
# Prompt 518 - comparison of two Prompt 517 filtered-summary snapshots
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY function comparing two snapshots
# recorded by `LearnedKnowledgeFilteredSummarySnapshotHistory` (Prompt
# 517). It is the same job `compare_learned_knowledge_diagnostic_
# snapshots()` (Prompt 509) does for Prompt 508 analysis snapshots,
# extended to the filtered-summary shape rather than duplicated: the
# same identity shape, the same invalid-input result shape, the same
# `direction`/`CHANGE_*` vocabulary, and the same numeric-entry shape
# (`{"earlier", "later", "delta", "changed"}`) are reused as-is.
#
# A filtered-summary snapshot does not carry a fixed set of analysis
# fields the way a Prompt 508 snapshot does - it carries whichever
# Prompt 515 sections were requested and available (Prompt 516/517),
# and two snapshots taken at different times may have requested, or
# had available, different sections. So this adds one extra dimension
# Prompt 509 does not need: for every real Prompt 515 section
# (`_SUMMARY_SECTIONS`), the comparison first records whether that
# section is `"present_in_both"`, `"present_only_earlier"`,
# `"present_only_later"`, or `"unavailable_in_both"` snapshot, using
# each snapshot's own `included_sections` exactly as recorded - nothing
# is inferred about *why* a section is missing (not requested vs.
# requested-but-unavailable are not distinguished, since Prompt 517
# itself does not keep that distinction either). Only sections that are
# `"present_in_both"` are actually compared; the rest are reported as
# such, with no value fabricated for the missing side.
#
# For a `"present_in_both"` section:
#   - `evaluation_counts` / `rates` - the shared numeric fields already
#     defined by Prompt 508/509 (`_ANALYSIS_COUNT_FIELDS` /
#     `_ANALYSIS_RATE_FIELDS`) get the exact same
#     `{"earlier", "later", "delta", "changed"}` entry Prompt 509 numeric
#     fields get, `delta = later - earlier`, merged into one flat
#     `"numeric"` dict at the top level (same key set Prompt 509 uses,
#     never a new metric).
#   - `dominant_rejection_reason` - the exact Prompt 509 categorical
#     comparison (`CHANGE_UNCHANGED` / `CHANGE_CHANGED` /
#     `CHANGE_BECAME_EMPTY` / `CHANGE_BECAME_AVAILABLE`), unchanged.
#   - `comparison_changes` / `trend` / `validation_statuses` - these are
#     already-composite Prompt 515 dicts (an embedded comparison
#     summary, a trend summary, a validation-status readout), not a
#     single scalar, so there is no new sub-metric to invent for them;
#     they are compared for exact equality only, reported with the same
#     `CHANGE_UNCHANGED` / `CHANGE_CHANGED` vocabulary Prompt 509 already
#     defines. This never re-derives, re-diffs field-by-field, scores, or
#     interprets what changed inside them - it only says whether the
#     recorded section value is the same or not.
#
# Nothing here labels a change good/bad, infers a cause, predicts future
# behavior, or generates a recommendation. Nothing here mutates `earlier`
# or `later`, touches any history/statistics/trace/learned record, or is
# wired into the gate/decision/response path.

FILTERED_COMPARISON_PRESENT_BOTH = "present_in_both"
FILTERED_COMPARISON_PRESENT_ONLY_EARLIER = "present_only_earlier"
FILTERED_COMPARISON_PRESENT_ONLY_LATER = "present_only_later"
FILTERED_COMPARISON_UNAVAILABLE_BOTH = "unavailable_in_both"

_FILTERED_COMPARISON_PRESENCE_STATES = (
    FILTERED_COMPARISON_PRESENT_BOTH,
    FILTERED_COMPARISON_PRESENT_ONLY_EARLIER,
    FILTERED_COMPARISON_PRESENT_ONLY_LATER,
    FILTERED_COMPARISON_UNAVAILABLE_BOTH,
)

# Sections whose "present in both" comparison decomposes into the shared
# Prompt 508/509 numeric fields, rather than being compared as one
# opaque value.
_FILTERED_NUMERIC_SECTION_FIELDS = {
    "evaluation_counts": _ANALYSIS_COUNT_FIELDS,
    "rates": _ANALYSIS_RATE_FIELDS,
}

_FILTERED_SNAPSHOT_REQUIRED_FIELDS = (
    "snapshot_id", "sequence", "snapshot_kind", "validation_status",
    "validation_errors", "included_sections", "unavailable_sections",
    "unknown_section_count", "metrics",
)


def _filtered_summary_snapshot_structural_errors(snapshot):
    """Structural problems with `snapshot` as a Prompt 517
    filtered-summary snapshot (as stored by
    `LearnedKnowledgeFilteredSummarySnapshotHistory`), as an ordered
    list of short codes (`[]` when well-formed). Mirrors Prompt 509's
    `_snapshot_structural_errors()` for the Prompt 517 shape. Never
    mutates `snapshot`; never raises."""
    if snapshot is None:
        return ["snapshot_missing"]
    if not isinstance(snapshot, dict):
        return ["snapshot_not_a_dict"]

    errors = [
        "missing_field:%s" % field
        for field in _FILTERED_SNAPSHOT_REQUIRED_FIELDS
        if field not in snapshot
    ]
    if errors:
        return errors

    if snapshot["snapshot_kind"] != SNAPSHOT_KIND_FILTERED_SUMMARY:
        errors.append("not_a_filtered_summary_snapshot")

    snapshot_id = snapshot["snapshot_id"]
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        errors.append("invalid_snapshot_id")

    sequence = snapshot["sequence"]
    if not _is_plain_int(sequence) or sequence < 1:
        errors.append("invalid_sequence")

    status = snapshot["validation_status"]
    if status not in _SNAPSHOT_STATUSES:
        errors.append("invalid_validation_status")

    validation_errors = snapshot["validation_errors"]
    if (not isinstance(validation_errors, list)
            or not all(isinstance(item, str) for item in validation_errors)):
        errors.append("invalid_validation_errors")
    elif status == SNAPSHOT_VALIDATION_VALID and validation_errors:
        errors.append("valid_snapshot_has_validation_errors")

    included = snapshot["included_sections"]
    unavailable = snapshot["unavailable_sections"]
    if not isinstance(included, list) or not isinstance(unavailable, list):
        errors.append("invalid_section_lists")
    else:
        names = included + unavailable
        if (any(not isinstance(name, str) or name not in _SUMMARY_SECTIONS for name in names)
                or len(set(names)) != len(names)):
            errors.append("invalid_section_names")
        if status == SNAPSHOT_VALIDATION_INVALID and included:
            errors.append("invalid_snapshot_has_included_sections")

    if not isinstance(snapshot["metrics"], dict):
        errors.append("invalid_metrics")

    unknown_count = snapshot["unknown_section_count"]
    if unknown_count is not None and not _is_plain_int(unknown_count):
        errors.append("invalid_unknown_section_count")

    return errors


def _filtered_snapshot_validation_information(snapshot):
    """Whatever of `snapshot`'s own validation information is usable, in
    the exact `_snapshot_validation_information()` (Prompt 509) shape.
    Nothing is invented: an unusable part is `None`."""
    if not isinstance(snapshot, dict):
        return None
    status = snapshot.get("validation_status")
    if not isinstance(status, str) or status not in _SNAPSHOT_STATUSES:
        status = None
    errors = snapshot.get("validation_errors")
    errors = copy.deepcopy(errors) if isinstance(errors, list) else None
    return {"validation_status": status, "validation_errors": errors}


def _filtered_snapshot_identity(snapshot):
    return {"snapshot_id": snapshot["snapshot_id"], "sequence": snapshot["sequence"]}


def _filtered_section_presence(section, earlier_included, later_included):
    in_earlier = section in earlier_included
    in_later = section in later_included
    if in_earlier and in_later:
        return FILTERED_COMPARISON_PRESENT_BOTH
    if in_earlier:
        return FILTERED_COMPARISON_PRESENT_ONLY_EARLIER
    if in_later:
        return FILTERED_COMPARISON_PRESENT_ONLY_LATER
    return FILTERED_COMPARISON_UNAVAILABLE_BOTH


def _filtered_numeric_field_entry(before, after):
    """The exact Prompt 509 numeric-field entry shape. Guarded (never
    raises) even though a `"present_in_both"` section's fields are
    already known-numeric by construction (Prompt 517 only ever copies
    them from a validated Prompt 515 section)."""
    if not (_is_finite_number(before) and _is_finite_number(after)):
        return {"earlier": before, "later": after, "delta": None, "changed": None}
    changed = before != after
    return {"earlier": before, "later": after, "delta": after - before, "changed": changed}


def _filtered_categorical_entry(before, after):
    """The exact Prompt 509 categorical comparison for a bare
    `str`/`None` value (`dominant_rejection_reason`)."""
    if before == after:
        change, changed = CHANGE_UNCHANGED, False
    elif before is None:
        change, changed = CHANGE_BECAME_AVAILABLE, True
    elif after is None:
        change, changed = CHANGE_BECAME_EMPTY, True
    else:
        change, changed = CHANGE_CHANGED, True
    return {"earlier": before, "later": after, "change": change, "changed": changed}


def _filtered_compound_entry(before, after):
    """Equality-only comparison for a composite Prompt 515 section value
    (`comparison_changes`, `trend`, `validation_statuses`) using the
    same Prompt 509 `CHANGE_UNCHANGED`/`CHANGE_CHANGED` vocabulary.
    Never diffs inside the value or interprets what changed."""
    changed = before != after
    return {
        "earlier": copy.deepcopy(before),
        "later": copy.deepcopy(after),
        "change": CHANGE_CHANGED if changed else CHANGE_UNCHANGED,
        "changed": changed,
    }


def _filtered_present_both_entry(section, before, after, numeric):
    if section in _FILTERED_NUMERIC_SECTION_FIELDS:
        field_names = _FILTERED_NUMERIC_SECTION_FIELDS[section]
        fields = {}
        any_changed = False
        for field in field_names:
            entry = _filtered_numeric_field_entry(
                before.get(field) if isinstance(before, dict) else None,
                after.get(field) if isinstance(after, dict) else None,
            )
            fields[field] = entry
            numeric[field] = entry
            if entry["changed"]:
                any_changed = True
        return {"fields": fields, "changed": any_changed}
    if section == "dominant_rejection_reason":
        entry = _filtered_categorical_entry(before, after)
        return dict(entry)
    entry = _filtered_compound_entry(before, after)
    return dict(entry)


def compare_learned_knowledge_filtered_summary_snapshots(earlier, later):
    """Deterministic, read-only comparison of two Prompt 517
    filtered-summary snapshots. `earlier` is the baseline and `later`
    the current one, exactly in the order given; every numeric delta is
    `later - earlier` (`"direction": "later_minus_earlier"`, the same
    `COMPARISON_DIRECTION` Prompt 509 uses). Returns a new, independent
    plain dict; never mutates `earlier` or `later`.

    Invalid input (either snapshot missing, not a dict, or not a
    well-formed Prompt 517 snapshot - see
    `_filtered_summary_snapshot_structural_errors()`) never raises and
    is never repaired; the result is exactly the Prompt 509 invalid
    shape:

        {
            "valid": False,
            "direction": "later_minus_earlier",
            "errors": ["earlier_snapshot_invalid", "later_snapshot_invalid"],
                                  # only those that apply, in that order
            "invalid_inputs": ["earlier", "later"],      # same, as roles
            "earlier_errors": [<structural error codes; [] if fine>],
            "later_errors": [<same>],
            "earlier_validation_information": <see Prompt 509>,
            "later_validation_information": <see Prompt 509>,
        }

    A structurally well-formed snapshot whose own `validation_status` is
    `"invalid"` is NOT a structural error (Prompt 517 already stores it
    that way on purpose) - it is simply a snapshot with no
    `included_sections`, so it contributes nothing "present" to the
    comparison and everything the other side has becomes
    `"present_only_..."`. That state is preserved, never repaired.

    Otherwise:

        {
            "valid": True,
            "errors": [],
            "direction": "later_minus_earlier",
            "earlier": {"snapshot_id": ..., "sequence": ...},   # baseline
            "later": {"snapshot_id": ..., "sequence": ...},     # current
            "chronological": <bool>,   # earlier.sequence < later.sequence
                                       # (informational only)
            "earlier_validation_status": "valid" | "invalid",
            "later_validation_status": "valid" | "invalid",
            "common_sections": [<Prompt 515 section names present in
                                  both snapshots, fixed order>],
            "identical": <bool>,  # no common section's value changed
            "changed_sections": [<common section that changed, fixed
                                   Prompt 515 section order>],
            "numeric": {
                "<field>": {"earlier": .., "later": ..,
                            "delta": later - earlier, "changed": <bool>},
                ...
            },  # the Prompt 508/509 numeric fields
                # (total_evaluations, accepted_count, rejected_count,
                # no_candidate_count, acceptance_rate, rejection_rate),
                # present only for a numeric field whose own section
                # (evaluation_counts / rates) is present in both snapshots
            "sections": {
                "<Prompt 515 section name>": {
                    "presence": "present_in_both" | "present_only_earlier"
                                | "present_only_later" | "unavailable_in_both",
                    ... comparison detail when "present_in_both" (see
                        below), or {"earlier": .., "later": ..} - the
                        one available side's exact value, `None` on the
                        missing side - otherwise,
                },
                ...
            },
        }

    For a `"present_in_both"` section, `sections[section]` additionally
    carries:
      - `evaluation_counts` / `rates`: `{"fields": {<field>: <numeric
        entry, same shape as "numeric">, ...}, "changed": <bool>}`;
      - `dominant_rejection_reason`: `{"earlier": .., "later": ..,
        "change": "unchanged"|"changed"|"became_empty"|"became_available",
        "changed": <bool>}` (the exact Prompt 509 categorical shape);
      - `comparison_changes` / `trend` / `validation_statuses`:
        `{"earlier": .., "later": .., "change": "unchanged"|"changed",
        "changed": <bool>}` - equality-only, since these are already
        composite Prompt 515 values with no single scalar to diff.

    A section absent from both snapshots (`"unavailable_in_both"`) is
    never fabricated: both sides are `None`. Deterministic: the same two
    snapshots always produce an equal result.
    """
    earlier_errors = _filtered_summary_snapshot_structural_errors(earlier)
    later_errors = _filtered_summary_snapshot_structural_errors(later)
    if earlier_errors or later_errors:
        invalid_inputs = []
        errors = []
        if earlier_errors:
            invalid_inputs.append("earlier")
            errors.append("earlier_snapshot_invalid")
        if later_errors:
            invalid_inputs.append("later")
            errors.append("later_snapshot_invalid")
        return {
            "valid": False,
            "direction": COMPARISON_DIRECTION,
            "errors": errors,
            "invalid_inputs": invalid_inputs,
            "earlier_errors": earlier_errors,
            "later_errors": later_errors,
            "earlier_validation_information": _filtered_snapshot_validation_information(earlier),
            "later_validation_information": _filtered_snapshot_validation_information(later),
        }

    earlier_included = earlier["included_sections"]
    later_included = later["included_sections"]
    earlier_metrics = earlier["metrics"]
    later_metrics = later["metrics"]

    sections = {}
    numeric = {}
    changed_sections = []
    common_sections = []

    for section in _SUMMARY_SECTIONS:
        presence = _filtered_section_presence(section, earlier_included, later_included)
        if presence == FILTERED_COMPARISON_PRESENT_BOTH:
            common_sections.append(section)
            before = earlier_metrics.get(section)
            after = later_metrics.get(section)
            detail = _filtered_present_both_entry(section, before, after, numeric)
            detail["presence"] = presence
            sections[section] = detail
            if detail.get("changed"):
                changed_sections.append(section)
        elif presence == FILTERED_COMPARISON_PRESENT_ONLY_EARLIER:
            sections[section] = {
                "presence": presence,
                "earlier": copy.deepcopy(earlier_metrics.get(section)),
                "later": None,
            }
        elif presence == FILTERED_COMPARISON_PRESENT_ONLY_LATER:
            sections[section] = {
                "presence": presence,
                "earlier": None,
                "later": copy.deepcopy(later_metrics.get(section)),
            }
        else:
            sections[section] = {"presence": presence, "earlier": None, "later": None}

    return {
        "valid": True,
        "errors": [],
        "direction": COMPARISON_DIRECTION,
        "earlier": _filtered_snapshot_identity(earlier),
        "later": _filtered_snapshot_identity(later),
        "chronological": earlier["sequence"] < later["sequence"],
        "earlier_validation_status": earlier["validation_status"],
        "later_validation_status": later["validation_status"],
        "common_sections": common_sections,
        "identical": not changed_sections,
        "changed_sections": changed_sections,
        "numeric": numeric,
        "sections": sections,
    }


# ----------------------------------------------------------------------
# Prompt 519 - validation of a Prompt 518 filtered-snapshot comparison
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY validator for the dict
# `compare_learned_knowledge_filtered_summary_snapshots()` (Prompt 518)
# returns. It is to Prompt 518 what
# `validate_learned_knowledge_diagnostic_snapshot_comparison()` (Prompt
# 510) is to Prompt 509: it reuses that validator's result shape
# (`valid` / `well_formed` / `errors` / `warnings`), its helpers
# (`_is_finite_number`, `_identity_is_well_formed`, `_is_bool`,
# `_validate_invalid_comparison`, `_NOT_PROVIDED`, ...) and its rules
# (delta is `later - earlier`; counts exact, rates within
# `_RATE_TOLERANCE`), and only adds what is specific to the filtered
# shape: per-section presence classification and the Prompt 518
# categorical vocabulary.
#
# It never repairs, regenerates, normalizes, reorders, or otherwise
# changes the comparison or either source snapshot, computes no new
# metric, passes no good/bad judgement on a change, reads no clock,
# randomness, network, or machine state, and is not called from the
# gate/decision/response path.
#
# Result (a new, independent dict) - the Prompt 510 keys plus the same
# errors split by kind, so a caller can tell the kinds apart without
# parsing codes:
#
#     {
#         "valid": <bool>,        # no errors at all
#         "well_formed": <bool>,  # the result is a faithful, internally
#                                 # consistent Prompt 518 result
#         "errors": [<str>, ...], # every error below, in the order:
#                                 # structural, section, numeric,
#                                 # categorical, ordering, source_snapshot
#         "warnings": [<str>, ...],
#         "structural_errors": [...],       # missing/malformed fields
#         "section_errors": [...],          # presence classification
#         "numeric_errors": [...],          # values / delta / changed
#         "categorical_errors": [...],      # states vs. values
#         "ordering_errors": [...],         # sequence/chronology
#         "source_snapshot_errors": [...],  # source refs / source status
#         "unavailable": [...],             # NOT errors: what could not
#                                           # be compared (see below)
#     }
#
# `well_formed` is `False` for anything that makes the result itself
# malformed or contradictory (structural, section, numeric, categorical
# errors, contradictory ordering metadata, a mismatch with a supplied
# source snapshot, an unusable source reference). It stays `True` when
# the result faithfully reports something about its inputs that keeps
# it from being *fully valid*: a source snapshot the comparison itself
# reports as invalid (`"source_snapshot_invalid:<role>"`), a source
# snapshot whose own `validation_status` is `"invalid"`
# (`"source_snapshot_validation_status_invalid:<role>"`), or a
# chronologically reversed pair (`"reversed_ordering"`).
#
# `unavailable` lists legitimate "nothing to compare" conditions - they
# are never errors and never make a result invalid:
#   "section_unavailable_in_both:<section>"
#   "insufficient_data:<section>"        (present in only one snapshot)
#   "no_shared_sections"
#   "no_comparable_numeric_metrics"
#   "numeric_value_unavailable:<field>.<earlier|later>"  (e.g. a rate
#                                         with zero evaluations)
#   "ordering_metadata_unavailable:<earlier|later>"
#
# Supported categorical states are exactly the ones Prompt 518 emits:
# `dominant_rejection_reason` uses unchanged / changed / became_empty /
# became_available; the composite sections use unchanged / changed.
# Anything else (including "insufficient_data", which Prompt 518 never
# puts on a comparison entry - it is reported in `unavailable` instead)
# is an `unsupported_categorical_state`.

_FILTERED_REASON_STATES = (
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY, CHANGE_BECAME_AVAILABLE,
)
_FILTERED_COMPOUND_STATES = (CHANGE_UNCHANGED, CHANGE_CHANGED)
_FILTERED_COMPARISON_VALID_REQUIRED = (
    "valid", "errors", "direction", "earlier", "later", "chronological",
    "earlier_validation_status", "later_validation_status", "common_sections",
    "identical", "changed_sections", "numeric", "sections",
)
_FILTERED_COMPARISON_KINDS = ("structural", "section", "numeric", "categorical", "ordering",
                              "source_snapshot")
_FILTERED_SECTION_ONE_SIDED_KEYS = ("presence", "earlier", "later")
_FILTERED_SECTION_NUMERIC_KEYS = ("presence", "fields", "changed")
_FILTERED_SECTION_CATEGORICAL_KEYS = ("presence", "earlier", "later", "change", "changed")
_FILTERED_NUMERIC_FIELD_TO_SECTION = {
    field: section
    for section, fields in _FILTERED_NUMERIC_SECTION_FIELDS.items()
    for field in fields
}


class _FilteredComparisonFindings(object):
    """Collects what the Prompt 519 validator finds, by kind. Internal."""

    def __init__(self):
        self.by_kind = {kind: [] for kind in _FILTERED_COMPARISON_KINDS}
        self.unavailable = []
        self.warnings = []
        self.malformed = False

    def add(self, kind, code, breaks_well_formed=True):
        if code not in self.by_kind[kind]:
            self.by_kind[kind].append(code)
        if breaks_well_formed:
            self.malformed = True

    def note_unavailable(self, code):
        if code not in self.unavailable:
            self.unavailable.append(code)


def _sorted_keys(mapping):
    return sorted(mapping.keys(), key=repr)


def _filtered_check_identity(role, identity, findings):
    """Checks one `earlier` / `later` identity; returns `(snapshot_id,
    sequence)` where a part is `None` if it is missing or unusable."""
    if not isinstance(identity, dict):
        findings.add("source_snapshot", "invalid_source_reference:%s" % role)
        findings.note_unavailable("ordering_metadata_unavailable:%s" % role)
        return None, None
    snapshot_id = identity.get("snapshot_id")
    sequence = identity.get("sequence")
    if "snapshot_id" not in identity or not isinstance(snapshot_id, str) or not snapshot_id.strip():
        findings.add("source_snapshot", "invalid_source_reference:%s" % role)
        snapshot_id = None
    if any(key not in ("snapshot_id", "sequence") for key in identity):
        findings.add("source_snapshot", "invalid_source_reference:%s" % role)
    if "sequence" not in identity:
        findings.add("ordering", "ordering_metadata_missing:%s" % role, breaks_well_formed=True)
        findings.note_unavailable("ordering_metadata_unavailable:%s" % role)
        sequence = None
    elif not _is_plain_int(sequence) or sequence < 1:
        findings.add("ordering", "invalid_ordering_metadata:%s" % role)
        findings.note_unavailable("ordering_metadata_unavailable:%s" % role)
        sequence = None
    return snapshot_id, sequence


def _filtered_check_ordering(comparison, earlier_id, earlier_seq, later_id, later_seq, findings):
    chronological = comparison.get("chronological")
    if "chronological" in comparison and not _is_bool(chronological):
        findings.add("structural", "invalid_type:chronological")
        chronological = None
    if earlier_seq is None or later_seq is None:
        return
    if earlier_seq > later_seq:
        findings.add("ordering", "reversed_ordering", breaks_well_formed=False)
    elif earlier_seq == later_seq:
        if earlier_id is not None and later_id is not None and earlier_id != later_id:
            findings.add("ordering", "contradictory_ordering:same_sequence_different_snapshot_id")
        elif earlier_id is not None and earlier_id == later_id:
            if "same_snapshot_compared" not in findings.warnings:
                findings.warnings.append("same_snapshot_compared")
    if earlier_id is not None and earlier_id == later_id and earlier_seq != later_seq:
        findings.add("ordering", "contradictory_ordering:same_snapshot_id_different_sequence")
    if chronological is not None and chronological != (earlier_seq < later_seq):
        findings.add("ordering", "contradictory_ordering:chronological_flag")


def _filtered_check_numeric_entry(field, entry, label, findings):
    """Checks one `{"earlier", "later", "delta", "changed"}` entry (Prompt
    509 shape). Nothing is repaired; the checks follow what Prompt 518
    reports: a delta and a changed flag exist exactly when both values
    are finite numbers."""
    if not isinstance(entry, dict):
        findings.add("numeric", "invalid_numeric_entry:%s" % label)
        return
    missing = [key for key in _NUMERIC_ENTRY_FIELDS if key not in entry]
    for key in missing:
        findings.add("numeric", "missing_numeric_entry_field:%s.%s" % (label, key))
    if missing:
        return
    if any(key not in _NUMERIC_ENTRY_FIELDS for key in entry):
        findings.add("numeric", "unexpected_numeric_entry_field:%s" % label)

    is_rate = field in _ANALYSIS_RATE_FIELDS
    before, after = entry["earlier"], entry["later"]
    delta, changed = entry["delta"], entry["changed"]
    values_ok = True
    for role, value in (("earlier", before), ("later", after)):
        if value is None:
            findings.note_unavailable("numeric_value_unavailable:%s.%s" % (field, role))
            values_ok = False
        elif _is_plain_number(value) and not math.isfinite(value):
            findings.add("numeric", "non_finite_value:%s.%s" % (label, role))
            values_ok = False
        elif not _is_finite_number(value) or (not is_rate and not _is_plain_int(value)):
            findings.add("numeric", "invalid_value_type:%s.%s" % (label, role))
            values_ok = False

    if values_ok:
        if not _is_plain_number(delta):
            findings.add("numeric", "invalid_delta_type:%s" % label)
        elif not math.isfinite(delta):
            findings.add("numeric", "non_finite_delta:%s" % label)
        elif not is_rate and not _is_plain_int(delta):
            findings.add("numeric", "invalid_delta_type:%s" % label)
        else:
            expected = after - before
            if is_rate:
                correct = math.isclose(delta, expected, rel_tol=_RATE_TOLERANCE,
                                       abs_tol=_RATE_TOLERANCE)
            else:
                correct = delta == expected
            if not correct:
                findings.add("numeric", "incorrect_delta:%s" % label)
        if not _is_bool(changed):
            findings.add("numeric", "invalid_changed_flag:%s" % label)
        elif changed != (before != after):
            findings.add("numeric", "inconsistent_changed:%s" % label)
    else:
        if delta is not None:
            findings.add("numeric", "delta_present_without_valid_values:%s" % label)
        if changed is not None:
            findings.add("numeric", "changed_present_without_valid_values:%s" % label)


def _filtered_expected_change(section, before, after):
    """(change, changed) Prompt 518 reports for two present values of a
    categorical / composite section - recomputed independently."""
    if section == "dominant_rejection_reason":
        if before == after:
            return CHANGE_UNCHANGED, False
        if before is None:
            return CHANGE_BECAME_AVAILABLE, True
        if after is None:
            return CHANGE_BECAME_EMPTY, True
        return CHANGE_CHANGED, True
    if before == after:
        return CHANGE_UNCHANGED, False
    return CHANGE_CHANGED, True


def _filtered_check_categorical_entry(section, entry, findings):
    if set(entry.keys()) != set(_FILTERED_SECTION_CATEGORICAL_KEYS):
        for key in _FILTERED_SECTION_CATEGORICAL_KEYS:
            if key not in entry:
                findings.add("structural", "missing_section_field:%s.%s" % (section, key))
        for key in _sorted_keys(entry):
            if key not in _FILTERED_SECTION_CATEGORICAL_KEYS:
                findings.add("structural", "unexpected_section_field:%s.%s" % (section, key))
        if any(key not in entry for key in _FILTERED_SECTION_CATEGORICAL_KEYS):
            return
    supported = (_FILTERED_REASON_STATES if section == "dominant_rejection_reason"
                 else _FILTERED_COMPOUND_STATES)
    change, changed = entry["change"], entry["changed"]
    change_ok = isinstance(change, str) and change in supported
    if not change_ok:
        findings.add("categorical", "unsupported_categorical_state:%s" % section)
    if not _is_bool(changed):
        findings.add("categorical", "invalid_changed_flag:%s" % section)
    if section == "dominant_rejection_reason":
        for role in ("earlier", "later"):
            if entry[role] is not None and not isinstance(entry[role], str):
                findings.add("categorical", "invalid_categorical_value:%s.%s" % (section, role))
    expected_change, expected_changed = _filtered_expected_change(
        section, entry["earlier"], entry["later"])
    if change_ok and change != expected_change:
        findings.add("categorical", "inconsistent_categorical_state:%s" % section)
    if _is_bool(changed) and changed != expected_changed:
        findings.add("categorical", "inconsistent_changed:%s" % section)


def _filtered_check_section_entry(section, entry, findings):
    """Checks one `sections[section]` entry and returns its presence
    (a supported state) or `None`."""
    if not isinstance(entry, dict):
        findings.add("structural", "invalid_section_entry:%s" % section)
        return None
    presence = entry.get("presence")
    if "presence" not in entry:
        findings.add("structural", "missing_section_field:%s.presence" % section)
        return None
    if not isinstance(presence, str) or presence not in _FILTERED_COMPARISON_PRESENCE_STATES:
        findings.add("section", "unsupported_presence_state:%s" % section)
        return None

    if presence == FILTERED_COMPARISON_PRESENT_BOTH:
        if section in _FILTERED_NUMERIC_SECTION_FIELDS:
            expected_keys = _FILTERED_SECTION_NUMERIC_KEYS
            for key in expected_keys:
                if key not in entry:
                    findings.add("structural", "missing_section_field:%s.%s" % (section, key))
            for key in _sorted_keys(entry):
                if key not in expected_keys:
                    findings.add("structural", "unexpected_section_field:%s.%s" % (section, key))
            if "changed" in entry and not _is_bool(entry["changed"]):
                findings.add("structural", "invalid_type:%s.changed" % section)
            fields = entry.get("fields")
            if "fields" in entry:
                if not isinstance(fields, dict):
                    findings.add("structural", "invalid_type:%s.fields" % section)
                else:
                    for field in _FILTERED_NUMERIC_SECTION_FIELDS[section]:
                        if field not in fields:
                            findings.add("numeric", "missing_numeric_entry:%s" % field)
                    for key in _sorted_keys(fields):
                        if key not in _FILTERED_NUMERIC_SECTION_FIELDS[section]:
                            findings.add("numeric", "unknown_numeric_field:%s" % _numeric_key_text(key))
        else:
            _filtered_check_categorical_entry(section, entry, findings)
    else:
        for key in _FILTERED_SECTION_ONE_SIDED_KEYS:
            if key not in entry:
                findings.add("structural", "missing_section_field:%s.%s" % (section, key))
        for key in _sorted_keys(entry):
            if key not in _FILTERED_SECTION_ONE_SIDED_KEYS:
                findings.add("structural", "unexpected_section_field:%s.%s" % (section, key))
        sides = {"earlier": presence != FILTERED_COMPARISON_PRESENT_ONLY_LATER
                 and presence != FILTERED_COMPARISON_UNAVAILABLE_BOTH,
                 "later": presence != FILTERED_COMPARISON_PRESENT_ONLY_EARLIER
                 and presence != FILTERED_COMPARISON_UNAVAILABLE_BOTH}
        for role in ("earlier", "later"):
            if not sides[role] and entry.get(role) is not None:
                findings.add(
                    "section", "contradictory_section_classification:%s:%s_value_present_for_%s"
                    % (section, role, presence))
    return presence


def _numeric_key_text(key):
    return key if isinstance(key, str) else repr(key)


def _filtered_check_top_level_lists(comparison, presences, findings):
    common = comparison.get("common_sections")
    changed_sections = comparison.get("changed_sections")
    sections = comparison.get("sections")

    def list_ok(name, value):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            findings.add("structural", "invalid_type:%s" % name)
            return False
        if any(item not in _SUMMARY_SECTIONS for item in value):
            findings.add("section", "unknown_section_in_%s" % name)
            return False
        if len(set(value)) != len(value):
            findings.add("section", "duplicate_section_in_%s" % name)
            return False
        if value != [s for s in _SUMMARY_SECTIONS if s in value]:
            findings.add("structural", "%s_out_of_order" % name)
            return False
        return True

    common_ok = "common_sections" in comparison and list_ok("common_sections", common)
    changed_ok = "changed_sections" in comparison and list_ok("changed_sections", changed_sections)

    if common_ok:
        for section in _SUMMARY_SECTIONS:
            presence = presences.get(section)
            if presence is None:
                continue
            listed = section in common
            shared = presence == FILTERED_COMPARISON_PRESENT_BOTH
            if listed and not shared:
                findings.add("section", "contradictory_section_classification:%s:"
                             "listed_common_but_%s" % (section, presence))
            elif shared and not listed:
                findings.add("section", "contradictory_section_classification:%s:"
                             "present_in_both_but_not_listed_common" % section)
    if changed_ok:
        for section in changed_sections:
            presence = presences.get(section)
            if presence is not None and presence != FILTERED_COMPARISON_PRESENT_BOTH:
                findings.add("section", "contradictory_section_classification:%s:"
                             "listed_changed_but_%s" % (section, presence))
            elif presence == FILTERED_COMPARISON_PRESENT_BOTH:
                entry = sections[section]
                if entry.get("changed") is not True:
                    findings.add("section", "changed_sections_mismatch:%s" % section)
        if common_ok and any(item not in common for item in changed_sections):
            findings.add("section", "changed_section_not_in_common_sections")
        # Every shared section that reports a change must be listed.
        for section in _SUMMARY_SECTIONS:
            if presences.get(section) == FILTERED_COMPARISON_PRESENT_BOTH:
                if sections[section].get("changed") is True and section not in changed_sections:
                    findings.add("section", "changed_sections_mismatch:%s" % section)
        if "identical" in comparison:
            if not _is_bool(comparison["identical"]):
                findings.add("structural", "invalid_type:identical")
            elif comparison["identical"] != (not changed_sections):
                findings.add("structural", "inconsistent_identical")
    elif "identical" in comparison and not _is_bool(comparison["identical"]):
        findings.add("structural", "invalid_type:identical")


def _filtered_check_numeric_block(comparison, presences, findings):
    numeric = comparison.get("numeric")
    sections = comparison.get("sections")
    if "numeric" not in comparison:
        return
    if not isinstance(numeric, dict):
        findings.add("structural", "invalid_type:numeric")
        return
    for field in _sorted_keys(numeric):
        if field not in _FILTERED_NUMERIC_FIELD_TO_SECTION:
            findings.add("numeric", "unknown_numeric_field:%s" % _numeric_key_text(field))
        elif presences.get(_FILTERED_NUMERIC_FIELD_TO_SECTION[field]) != FILTERED_COMPARISON_PRESENT_BOTH \
                and _FILTERED_NUMERIC_FIELD_TO_SECTION[field] in presences:
            findings.add("section", "contradictory_section_classification:%s:"
                         "numeric_field_without_shared_section" % field)
    for section, fields in _FILTERED_NUMERIC_SECTION_FIELDS.items():
        if presences.get(section) != FILTERED_COMPARISON_PRESENT_BOTH:
            continue
        section_fields = sections[section].get("fields")
        section_fields = section_fields if isinstance(section_fields, dict) else {}
        for field in fields:
            top = numeric.get(field, _NOT_PROVIDED)
            detail = section_fields.get(field, _NOT_PROVIDED)
            if top is _NOT_PROVIDED:
                findings.add("numeric", "missing_numeric_entry:%s" % field)
            else:
                _filtered_check_numeric_entry(field, top, field, findings)
            if detail is not _NOT_PROVIDED:
                if top is _NOT_PROVIDED or detail != top:
                    if top is not _NOT_PROVIDED:
                        findings.add("numeric", "numeric_section_mismatch:%s" % field)
                    _filtered_check_numeric_entry(field, detail, "%s.%s" % (section, field), findings)
        if isinstance(sections[section].get("changed"), bool):
            expected = any(
                isinstance(section_fields.get(field), dict) and section_fields[field].get("changed") is True
                for field in fields)
            if sections[section]["changed"] != expected:
                findings.add("numeric", "inconsistent_changed:%s" % section)


# Prompt 535 - the two source snapshots a filtered comparison names,
# judged directly (not only through what the comparison itself says).
# The comparison's own ordering (Prompt 519) is judged from the
# sequences it records; when the caller also hands in the actual source
# snapshots, THEIR sequences must put `earlier` strictly before `later`
# too, so a caller (or a comparison) that has the two snapshots in the
# wrong roles is reported as an ordering problem, not only as a
# scattering of identity/section mismatches. Reads the snapshots only;
# nothing is reordered, repaired, or re-derived.

def _filtered_check_source_ordering(earlier, later, findings):
    earlier_seq, later_seq = earlier["sequence"], later["sequence"]
    earlier_id, later_id = earlier["snapshot_id"], later["snapshot_id"]
    if earlier_seq > later_seq:
        # A comparison that itself records the reversed order is already
        # `reversed_ordering`; the sources add a finding only when the
        # comparison's own ordering did not.
        if "reversed_ordering" not in findings.by_kind["ordering"]:
            findings.add("ordering", "reversed_source_snapshots", breaks_well_formed=False)
    elif earlier_seq == later_seq and earlier_id != later_id:
        findings.add("ordering",
                     "contradictory_source_ordering:same_sequence_different_snapshot_id")
    if earlier_id == later_id and earlier_seq != later_seq:
        findings.add("ordering",
                     "contradictory_source_ordering:same_snapshot_id_different_sequence")


def _filtered_check_against_sources(comparison, presences, sources, findings):
    """Cross-checks a valid comparison against the source snapshots the
    caller supplied (`sources` maps role -> snapshot, only for provided
    ones). Reads the snapshots only."""
    usable = {}
    for role in _COMPARISON_ROLES:
        if role not in sources:
            continue
        snapshot = sources[role]
        problems = _filtered_summary_snapshot_structural_errors(snapshot)
        if snapshot is None:
            findings.add("source_snapshot", "source_snapshot_missing:%s" % role)
        elif problems:
            findings.add("source_snapshot", "comparison_valid_but_source_invalid:%s" % role)
        else:
            usable[role] = snapshot
    for role, snapshot in usable.items():
        if comparison.get(role) != _filtered_snapshot_identity(snapshot):
            findings.add("source_snapshot", "source_mismatch:%s:identity" % role)
        status_key = role + "_validation_status"
        if status_key in comparison and comparison[status_key] != snapshot["validation_status"]:
            findings.add("source_snapshot", "source_mismatch:%s:validation_status" % role)
        if snapshot["validation_status"] == SNAPSHOT_VALIDATION_INVALID:
            # Prompt 535: a comparison marked valid may not rest on a
            # source snapshot whose own status is invalid, whatever
            # status the comparison recorded for it.
            findings.add("source_snapshot",
                         "source_snapshot_validation_status_invalid:%s" % role,
                         breaks_well_formed=False)
    if "earlier" in usable and "later" in usable:
        _filtered_check_source_ordering(usable["earlier"], usable["later"], findings)

    sections = comparison.get("sections")
    for section in _SUMMARY_SECTIONS:
        presence = presences.get(section)
        if presence is None:
            continue
        in_earlier = section in usable["earlier"]["included_sections"] if "earlier" in usable else None
        in_later = section in usable["later"]["included_sections"] if "later" in usable else None
        if presence == FILTERED_COMPARISON_PRESENT_BOTH:
            if in_earlier is False:
                findings.add("section", "shared_section_not_in_source:%s:earlier" % section)
            if in_later is False:
                findings.add("section", "shared_section_not_in_source:%s:later" % section)
        elif presence == FILTERED_COMPARISON_PRESENT_ONLY_EARLIER:
            if in_later is True:
                findings.add("section", "earlier_only_section_in_later_source:%s" % section)
            if in_earlier is False:
                findings.add("section", "earlier_only_section_not_in_earlier_source:%s" % section)
        elif presence == FILTERED_COMPARISON_PRESENT_ONLY_LATER:
            if in_earlier is True:
                findings.add("section", "later_only_section_in_earlier_source:%s" % section)
            if in_later is False:
                findings.add("section", "later_only_section_not_in_later_source:%s" % section)
        else:
            for role, present in (("earlier", in_earlier), ("later", in_later)):
                if present is True:
                    findings.add("section", "unavailable_section_in_source:%s:%s" % (section, role))

        # Recorded values must be the source's own values.
        entry = sections[section]
        for role in ("earlier", "later"):
            if role not in usable:
                continue
            snapshot = usable[role]
            if section not in snapshot["included_sections"]:
                continue
            source_value = snapshot["metrics"].get(section)
            if section in _FILTERED_NUMERIC_SECTION_FIELDS:
                fields = entry.get("fields") if presence == FILTERED_COMPARISON_PRESENT_BOTH else None
                if isinstance(fields, dict):
                    for field in _FILTERED_NUMERIC_SECTION_FIELDS[section]:
                        detail = fields.get(field)
                        source_field = source_value.get(field) if isinstance(source_value, dict) else None
                        if isinstance(detail, dict) and role in detail and detail[role] != source_field:
                            findings.add("numeric", "source_mismatch:%s:%s" % (role, field))
                elif presence != FILTERED_COMPARISON_PRESENT_BOTH and role in entry \
                        and entry[role] != source_value:
                    findings.add("numeric", "source_mismatch:%s:%s" % (role, section))
            elif role in entry and entry[role] != source_value:
                findings.add("categorical", "source_mismatch:%s:%s" % (role, section))


def _filtered_check_sections_block(comparison, findings):
    """Returns `{section: presence}` for every well-classified section."""
    presences = {}
    if "sections" not in comparison:
        return presences
    sections = comparison["sections"]
    if not isinstance(sections, dict):
        findings.add("structural", "invalid_type:sections")
        return presences
    for name in _sorted_keys(sections):
        if name not in _SUMMARY_SECTIONS:
            findings.add("section", "unknown_section:%s" % _numeric_key_text(name))
    for section in _SUMMARY_SECTIONS:
        if section not in sections:
            findings.add("structural", "missing_section_entry:%s" % section)
            continue
        presence = _filtered_check_section_entry(section, sections[section], findings)
        if presence is not None:
            presences[section] = presence
    return presences


def _filtered_note_unavailable(comparison, presences, findings):
    for section in _SUMMARY_SECTIONS:
        presence = presences.get(section)
        if presence == FILTERED_COMPARISON_UNAVAILABLE_BOTH:
            findings.note_unavailable("section_unavailable_in_both:%s" % section)
        elif presence in (FILTERED_COMPARISON_PRESENT_ONLY_EARLIER,
                          FILTERED_COMPARISON_PRESENT_ONLY_LATER):
            findings.note_unavailable("insufficient_data:%s" % section)
    if presences and not any(p == FILTERED_COMPARISON_PRESENT_BOTH for p in presences.values()):
        findings.note_unavailable("no_shared_sections")
    numeric = comparison.get("numeric")
    if isinstance(numeric, dict) and not numeric:
        findings.note_unavailable("no_comparable_numeric_metrics")


def _filtered_validate_valid_comparison(comparison, sources, findings):
    for field in _FILTERED_COMPARISON_VALID_REQUIRED:
        if field not in comparison:
            findings.add("structural", "missing_field:%s" % field)
    if "errors" in comparison and comparison["errors"] != []:
        findings.add("structural", "invalid_errors_for_valid_comparison")
    if "direction" in comparison and comparison["direction"] != COMPARISON_DIRECTION:
        findings.add("structural", "invalid_direction")

    earlier_id, earlier_seq = (
        _filtered_check_identity("earlier", comparison["earlier"], findings)
        if "earlier" in comparison else (None, None))
    later_id, later_seq = (
        _filtered_check_identity("later", comparison["later"], findings)
        if "later" in comparison else (None, None))
    _filtered_check_ordering(comparison, earlier_id, earlier_seq, later_id, later_seq, findings)

    for role in _COMPARISON_ROLES:
        key = role + "_validation_status"
        if key not in comparison:
            continue
        status = comparison[key]
        if not isinstance(status, str) or status not in _SNAPSHOT_STATUSES:
            findings.add("structural", "invalid_%s" % key)
        elif status == SNAPSHOT_VALIDATION_INVALID:
            findings.add("source_snapshot",
                         "source_snapshot_validation_status_invalid:%s" % role,
                         breaks_well_formed=False)

    presences = _filtered_check_sections_block(comparison, findings)
    if "common_sections" in comparison or "changed_sections" in comparison:
        _filtered_check_top_level_lists(comparison, presences, findings)
    _filtered_check_numeric_block(comparison, presences, findings)
    _filtered_note_unavailable(comparison, presences, findings)
    if sources:
        _filtered_check_against_sources(comparison, presences, sources, findings)


def _filtered_validate_invalid_comparison(comparison, sources, findings):
    structural, source_errors = [], []
    _validate_invalid_comparison(comparison, structural, source_errors)
    for code in structural:
        findings.add("structural", code)
    for code in source_errors:
        findings.add("source_snapshot", code, breaks_well_formed=False)
    for role, snapshot in sources.items():
        problems = _filtered_summary_snapshot_structural_errors(snapshot)
        if comparison.get(role + "_errors") != problems:
            findings.add("source_snapshot", "source_errors_mismatch:%s" % role)


def validate_learned_knowledge_filtered_summary_snapshot_comparison(
        comparison, earlier_snapshot=_NOT_PROVIDED, later_snapshot=_NOT_PROVIDED):
    """Deterministic, read-only validation of `comparison` - the dict
    `compare_learned_knowledge_filtered_summary_snapshots()` (Prompt 518)
    returns. See the block comment above for the result shape and the
    exact meaning of `valid`, `well_formed`, the per-kind error lists,
    and `unavailable`.

    What is checked (valid comparison branch): every Prompt 518 field is
    present with the right type; `direction`; both source identities
    and their ordering metadata (missing, reversed, or contradictory
    sequence / `chronological` data is reported, never reordered); the
    two recorded `validation_status` values (a source snapshot whose own
    status is `"invalid"` can never yield a fully valid comparison);
    every section's `presence` classification and that it agrees with
    `common_sections`, `changed_sections`, `numeric`, and the other
    sections' data (no section is classified two ways, and a one-sided
    or unavailable section carries no value for the missing side);
    every numeric entry (finite numeric values; `delta ==
    later - earlier` - exact for counts, within Prompt 506's rate
    tolerance for rates; `changed` agrees; a delta/flag only when both
    values are numbers, so zero-evaluation `None` rates are valid);
    every categorical state (only the states Prompt 518 emits, and each
    agrees with the values it compares).

    What is checked (invalid comparison branch): the same as Prompt
    510 - the Prompt 518 invalid shape is internally consistent, and the
    comparison is reported as `"source_snapshot_invalid:<role>"`.

    If `earlier_snapshot` / `later_snapshot` are given (`None` means
    "the referenced snapshot does not exist"), the comparison is also
    cross-checked against them: identity, validation status, section
    presence, and recorded values must all be derivable from them.

    Prompt 535 extends that cross-check to the two sources themselves:
    the given snapshots' own sequences must put `earlier` strictly
    before `later` (`"reversed_source_snapshots"`, `"contradictory_
    source_ordering:<why>"`, kind `ordering`); a source snapshot whose
    own `validation_status` is `"invalid"` cannot back a comparison
    marked valid (`"source_snapshot_validation_status_invalid:<role>"`,
    whatever status the comparison recorded); a missing (`None`)
    source is `"source_snapshot_missing:<role>"`; and a source that is
    not the snapshot the comparison names, or a section (the filtered
    `trend` included) recorded from the wrong source, stays a
    `"source_mismatch:..."`, `"shared_section_not_in_source:..."` etc.
    error. All of it reads the snapshots only, adds no metric, and never
    repairs or reorders anything.

    Never repairs, regenerates, or otherwise changes `comparison` or
    the snapshots; a non-dict `comparison` safely yields
    `"comparison_not_a_dict"`. Deterministic: the same inputs always
    give an equal result.
    """
    findings = _FilteredComparisonFindings()
    sources = {}
    if earlier_snapshot is not _NOT_PROVIDED:
        sources["earlier"] = earlier_snapshot
    if later_snapshot is not _NOT_PROVIDED:
        sources["later"] = later_snapshot

    if not isinstance(comparison, dict):
        findings.add("structural", "comparison_not_a_dict")
    elif "valid" not in comparison:
        findings.add("structural", "missing_field:valid")
    elif not _is_bool(comparison["valid"]):
        findings.add("structural", "invalid_type:valid")
    elif comparison["valid"]:
        _filtered_validate_valid_comparison(comparison, sources, findings)
    else:
        _filtered_validate_invalid_comparison(comparison, sources, findings)

    kinds = findings.by_kind
    errors = []
    for kind in _FILTERED_COMPARISON_KINDS:
        errors.extend(kinds[kind])
    return {
        "valid": not errors,
        "well_formed": not findings.malformed,
        "errors": errors,
        "warnings": list(findings.warnings),
        "structural_errors": list(kinds["structural"]),
        "section_errors": list(kinds["section"]),
        "numeric_errors": list(kinds["numeric"]),
        "categorical_errors": list(kinds["categorical"]),
        "ordering_errors": list(kinds["ordering"]),
        "source_snapshot_errors": list(kinds["source_snapshot"]),
        "unavailable": list(findings.unavailable),
    }


# ----------------------------------------------------------------------
# Prompt 520 - trend summary over Prompt 518 filtered-snapshot comparisons
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY function over an ORDERED collection of
# filtered-snapshot comparison results (the dicts
# `compare_learned_knowledge_filtered_summary_snapshots()` (Prompt 518)
# returns). It is to Prompt 518/519 what
# `summarize_learned_knowledge_diagnostic_snapshot_comparison_trend()`
# (Prompt 511) is to Prompt 509/510, and it reuses that design rather than
# duplicating it: the same result envelope (`valid` / `errors` /
# `direction` / `total_comparisons` / `eligible_count` /
# `ineligible_count` / `ineligible_comparisons` / `chronological_range`
# / `validation_status`), the same state vocabulary (`TREND_INCREASED`,
# `TREND_DECREASED`, `TREND_INSUFFICIENT_DATA`, and the Prompt 509
# `CHANGE_*` states), and the same state helpers
# (`_numeric_trend_state()`, `_categorical_trend_state()`,
# `_validation_status_trend()`). Each comparison is judged by the Prompt
# 519 validator (called, not reimplemented); only comparisons that pass
# are eligible, and the rest are reported by input position together
# with the exact Prompt 519 errors - never repaired, guessed at, or
# silently dropped. (In this summary "eligible" = valid and "ineligible"
# = invalid.)
#
# What is new is only what a filtered comparison needs: a metric or
# section may be present in some comparisons and not others, because
# each filtered snapshot carries only the sections that were selected.
# So every numeric metric and every section gets an `"availability"`
# reading over the eligible comparisons, and a trend is computed only
# from the comparisons where the metric was actually comparable (the
# earliest such comparison's "earlier" value against the latest such
# comparison's "later" value, in the order supplied). Nothing is ever
# filled in for a comparison where a value is missing.
#
# Availability states (per metric / section, over eligible comparisons):
#   "consistently_available"      comparable in every eligible comparison
#   "intermittently_available"    comparable in some, with a gap
#   "only_available_earlier"      comparable only in a leading run
#   "only_available_later"        comparable only in a trailing run
#   "unavailable"                 comparable in none of them
#   "invalid"                     comparisons were given but none was valid
#
# A section counts as available in a comparison when its `presence` is
# `"present_in_both"`; a numeric metric when its entry has finite earlier
# and later values.
#
# Chronology: comparisons are never re-sorted. The eligible comparisons'
# snapshot sequences are checked in the given order; a comparison whose
# "earlier" or "later" sequence is lower than the previous eligible
# comparison's is reported in `chronology["reversed"]` and
# `chronology["ordered"]` is `False`. Comparisons that are themselves
# reversed fail Prompt 519 validation (`"reversed_ordering"`) and are
# ineligible. When the eligible comparisons are not in order, no numeric
# or categorical trend is reported (each is `"insufficient_data"`, code
# `"chronology_not_ordered"` in `unavailable`) rather than a trend over a
# sequence that cannot be trusted; availability is still reported.
#
# Categorical states reuse Prompt 518's own vocabulary:
# `dominant_rejection_reason` -> unchanged / changed / became_available
# ("appeared") / became_empty ("disappeared") / insufficient_data; the
# composite sections (`comparison_changes`, `trend`,
# `validation_statuses`) -> unchanged / changed / insufficient_data
# (equality only, as in Prompt 518). Each also lists the states the
# individual comparisons reported (`observed_states`), so no distinction
# a comparison made is lost.
#
# What this is not: not a prediction, forecast, recommendation, score,
# rank, grade, or judgement of any state, and not a second validation or
# history system. Never mutates `comparisons` or any comparison in it;
# every returned value is an independent copy. Not called from the
# gate/decision/response path. Deterministic: the same ordered input
# always yields an equal result.

AVAILABILITY_CONSISTENT = "consistently_available"
AVAILABILITY_INTERMITTENT = "intermittently_available"
AVAILABILITY_ONLY_EARLIER = "only_available_earlier"
AVAILABILITY_ONLY_LATER = "only_available_later"
AVAILABILITY_UNAVAILABLE = "unavailable"
AVAILABILITY_INVALID = "invalid"

_FILTERED_TREND_CATEGORICAL_SECTIONS = (
    "dominant_rejection_reason", "comparison_changes", "trend", "validation_statuses",
)


def _filtered_trend_availability(flags, has_comparisons):
    """Availability state for `flags` - one bool per ELIGIBLE comparison,
    in order."""
    if not flags:
        return AVAILABILITY_INVALID if has_comparisons else AVAILABILITY_UNAVAILABLE
    if all(flags):
        return AVAILABILITY_CONSISTENT
    if not any(flags):
        return AVAILABILITY_UNAVAILABLE
    first = flags.index(True)
    last = len(flags) - 1 - flags[::-1].index(True)
    if all(flags[first:last + 1]):
        if first == 0:
            return AVAILABILITY_ONLY_EARLIER
        if last == len(flags) - 1:
            return AVAILABILITY_ONLY_LATER
    return AVAILABILITY_INTERMITTENT


def _filtered_trend_chronology(eligible):
    """`eligible` is `[(input_index, comparison), ...]`. Reports, never
    corrects, an eligible comparison whose snapshot sequences go backwards
    relative to the previous eligible one."""
    reversed_entries = []
    for position in range(1, len(eligible)):
        previous_index, previous = eligible[position - 1]
        index, current = eligible[position]
        if (current["earlier"]["sequence"] < previous["earlier"]["sequence"]
                or current["later"]["sequence"] < previous["later"]["sequence"]):
            reversed_entries.append({"index": index, "previous_index": previous_index})
    return {"ordered": not reversed_entries, "reversed": reversed_entries}


def _filtered_numeric_available(comparison, field):
    entry = comparison["numeric"].get(field)
    return (isinstance(entry, dict) and _is_finite_number(entry.get("earlier"))
            and _is_finite_number(entry.get("later")) and _is_finite_number(entry.get("delta")))


def _filtered_section_available(comparison, section):
    return comparison["sections"][section]["presence"] == FILTERED_COMPARISON_PRESENT_BOTH


def _filtered_numeric_trend_entry(field, eligible, ordered, has_comparisons):
    flags = [_filtered_numeric_available(c, field) for _, c in eligible]
    available = [(i, c) for (i, c), ok in zip(eligible, flags) if ok]
    entry = {"state": TREND_INSUFFICIENT_DATA, "start": None, "end": None, "delta": None}
    if available and ordered:
        start = available[0][1]["numeric"][field]["earlier"]
        end = available[-1][1]["numeric"][field]["later"]
        entry = {"state": _numeric_trend_state(start, end), "start": start, "end": end,
                 "delta": end - start}
    entry["availability"] = _filtered_trend_availability(flags, has_comparisons)
    entry["available_in"] = [i for i, _ in available]
    return entry


def _filtered_categorical_trend_entry(section, eligible, ordered, has_comparisons):
    flags = [_filtered_section_available(c, section) for _, c in eligible]
    available = [(i, c) for (i, c), ok in zip(eligible, flags) if ok]
    reason = section == "dominant_rejection_reason"
    entry = {"state": TREND_INSUFFICIENT_DATA}
    if reason:
        entry.update({"start": None, "end": None})
    if available and ordered:
        start = available[0][1]["sections"][section]["earlier"]
        end = available[-1][1]["sections"][section]["later"]
        entry["state"] = _categorical_trend_state(start, end, reason)
        if reason:
            entry["start"], entry["end"] = start, end
    entry["availability"] = _filtered_trend_availability(flags, has_comparisons)
    entry["available_in"] = [i for i, _ in available]
    entry["observed_states"] = [
        {"index": i, "change": c["sections"][section]["change"]} for i, c in available]
    return entry


def _filtered_section_availability_entry(section, eligible, has_comparisons):
    flags = [_filtered_section_available(c, section) for _, c in eligible]
    counts = {state: 0 for state in _FILTERED_COMPARISON_PRESENCE_STATES}
    for _, comparison in eligible:
        counts[comparison["sections"][section]["presence"]] += 1
    return {
        "availability": _filtered_trend_availability(flags, has_comparisons),
        "available_in": [i for (i, _), ok in zip(eligible, flags) if ok],
        "presence_counts": counts,
    }


def summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend(comparisons):
    """Deterministic, read-only trend summary over `comparisons` - an
    ORDERED collection (oldest first) of Prompt 518 comparison dicts.
    `None` or `[]` is an empty history; the given order is never changed.
    A non-list/tuple argument yields `"valid": False` with
    `"comparisons_not_a_sequence"` and no trends. Returns a new,
    independent plain dict:

        {
            "valid": True, "errors": [], "direction": "later_minus_earlier",
            "total_comparisons": <int>,
            "eligible_count": <int>,          # passed Prompt 519 validation
            "ineligible_count": <int>,
            "ineligible_comparisons": [{"index": <int>, "errors": [<str>, ...]}],
                                              # the Prompt 519 errors, input order
            "chronological_range": {"earlier": <identity>|None, "later": <identity>|None},
            "chronology": {"ordered": <bool>,
                           "reversed": [{"index": <int>, "previous_index": <int>}]},
            "numeric": {"<field>": {"state": "increased"|"decreased"|"unchanged"
                                             |"insufficient_data",
                                    "start": .., "end": .., "delta": ..,
                                    "availability": <state>,
                                    "available_in": [<input index>, ...]}},
                        # the six Prompt 508 numeric fields
            "categorical": {"<section>": {"state": ..., ["start", "end"] (reason only),
                                          "availability": <state>, "available_in": [...],
                                          "observed_states": [{"index", "change"}]}},
                        # dominant_rejection_reason, comparison_changes, trend,
                        # validation_statuses
            "section_availability": {"<Prompt 515 section>": {
                "availability": <state>, "available_in": [...],
                "presence_counts": {<presence state>: <int>}}},
            "validation_status": <Prompt 511 shape: first vs last comparison passed 519>,
            "unavailable": [<str>, ...],
                # "no_comparisons", "no_eligible_comparisons",
                # "chronology_not_ordered", "insufficient_data:<metric or section>"
        }

    Everything is descriptive: no cause, prediction, recommendation,
    score, rank, or good/bad reading is produced. Never mutates any
    input.
    """
    if comparisons is not None and not isinstance(comparisons, (list, tuple)):
        return {"valid": False, "errors": ["comparisons_not_a_sequence"],
                "direction": COMPARISON_DIRECTION}
    comparisons = list(comparisons) if comparisons else []
    has_comparisons = bool(comparisons)

    validations = []
    eligible = []
    ineligible_comparisons = []
    for index, comparison in enumerate(comparisons):
        validation = validate_learned_knowledge_filtered_summary_snapshot_comparison(comparison)
        validations.append(validation)
        if validation["valid"]:
            eligible.append((index, comparison))
        else:
            ineligible_comparisons.append({"index": index, "errors": list(validation["errors"])})

    chronology = _filtered_trend_chronology(eligible)
    ordered = chronology["ordered"]

    numeric = {field: _filtered_numeric_trend_entry(field, eligible, ordered, has_comparisons)
               for field in _TREND_NUMERIC_FIELDS}
    categorical = {section: _filtered_categorical_trend_entry(section, eligible, ordered, has_comparisons)
                   for section in _FILTERED_TREND_CATEGORICAL_SECTIONS}
    section_availability = {
        section: _filtered_section_availability_entry(section, eligible, has_comparisons)
        for section in _SUMMARY_SECTIONS}

    unavailable = []
    if not has_comparisons:
        unavailable.append("no_comparisons")
    elif not eligible:
        unavailable.append("no_eligible_comparisons")
    if not ordered:
        unavailable.append("chronology_not_ordered")
    for field in _TREND_NUMERIC_FIELDS:
        if numeric[field]["state"] == TREND_INSUFFICIENT_DATA:
            unavailable.append("insufficient_data:%s" % field)
    for section in _FILTERED_TREND_CATEGORICAL_SECTIONS:
        if categorical[section]["state"] == TREND_INSUFFICIENT_DATA:
            unavailable.append("insufficient_data:%s" % section)

    chronological_range = {
        "earlier": copy.deepcopy(eligible[0][1]["earlier"]) if eligible else None,
        "later": copy.deepcopy(eligible[-1][1]["later"]) if eligible else None,
    }
    return {
        "valid": True,
        "errors": [],
        "direction": COMPARISON_DIRECTION,
        "total_comparisons": len(comparisons),
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible_comparisons),
        "ineligible_comparisons": ineligible_comparisons,
        "chronological_range": chronological_range,
        "chronology": chronology,
        "numeric": numeric,
        "categorical": categorical,
        "section_availability": section_availability,
        "validation_status": _validation_status_trend(validations),
        "unavailable": unavailable,
    }


# ----------------------------------------------------------------------
# Prompt 521 - validation of a Prompt 520 filtered diagnostic trend summary
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY validator for the dict
# `summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend()`
# (Prompt 520) returns. It is to Prompt 520 what
# `validate_learned_knowledge_diagnostic_snapshot_comparison_trend()`
# (Prompt 512) is to Prompt 511, and it reuses that design rather than
# duplicating it: the same result envelope (`valid` / `well_formed` /
# `errors` / `warnings`), the same generic helpers (`_is_nonneg_int`,
# `_check_ineligible_comparisons`, `_check_trend_chronological_range`,
# `_check_trend_categorical_entry`, `_is_finite_number`, `_is_list_of_str`,
# `_is_bool`), and the same optional-`comparisons` cross-check pattern.
#
# What is new is only what the filtered trend shape (Prompt 520) needs on
# top of the Prompt 511/512 shape: per-metric/per-section `"availability"`
# and `"available_in"`, an explicit `"chronology"` block (Prompt 511 only
# has `"chronological_range"`), a `"section_availability"` block, and
# `"observed_states"` on every categorical entry. Each of these is
# checked for internal consistency using only the trend summary's own
# declared fields (the eligible input positions can always be derived
# from `total_comparisons` and `ineligible_comparisons`, without needing
# the real source comparisons) - the same "well-formed on its own" idea
# Prompt 512 already uses for its structural checks. A composite
# categorical section (`comparison_changes`, `trend`,
# `validation_statuses`) keeps no scalar value in the trend entry itself
# (only `dominant_rejection_reason` retains `start`/`end`), so its trend
# *state* can only be fully cross-checked against real data when the
# caller also supplies `comparisons` - exactly like Prompt 512's own
# `"mismatched_field"` / `"mismatched_numeric"` cross-check.
#
# Never repairs, regenerates, reorders, or otherwise changes
# `trend_summary` or `comparisons`; never mutates either. Not called from
# the gate/decision/response path; produces no prediction, recommendation,
# score, rank, or good/bad judgement. Deterministic: the same inputs
# always give an equal result.

_FILTERED_TREND_REQUIRED_FIELDS = (
    "valid", "errors", "direction", "total_comparisons", "eligible_count",
    "ineligible_count", "ineligible_comparisons", "chronological_range",
    "chronology", "numeric", "categorical", "section_availability",
    "validation_status", "unavailable",
)
_FILTERED_TREND_NUMERIC_ENTRY_FIELDS = (
    "state", "start", "end", "delta", "availability", "available_in")
_FILTERED_TREND_REASON_ENTRY_FIELDS = (
    "state", "start", "end", "availability", "available_in", "observed_states")
_FILTERED_TREND_COMPOUND_ENTRY_FIELDS = (
    "state", "availability", "available_in", "observed_states")
_FILTERED_TREND_SECTION_AVAILABILITY_FIELDS = ("availability", "available_in", "presence_counts")
_FILTERED_TREND_CHRONOLOGY_FIELDS = ("ordered", "reversed")
_FILTERED_TREND_REVERSED_ENTRY_FIELDS = ("index", "previous_index")
_FILTERED_TREND_AVAILABILITY_STATES = (
    AVAILABILITY_CONSISTENT, AVAILABILITY_INTERMITTENT, AVAILABILITY_ONLY_EARLIER,
    AVAILABILITY_ONLY_LATER, AVAILABILITY_UNAVAILABLE, AVAILABILITY_INVALID,
)


def _filtered_trend_eligible_indices(trend_summary):
    """The ascending list of original input positions the trend summary
    claims are eligible, derived purely from its own declared
    `total_comparisons` / `ineligible_comparisons` fields - `None` when
    either is not well-formed enough to derive this safely (that is
    already reported elsewhere as a structural error)."""
    total = trend_summary.get("total_comparisons")
    ineligible = trend_summary.get("ineligible_comparisons")
    if not _is_nonneg_int(total) or not isinstance(ineligible, list):
        return None
    bad = set()
    for entry in ineligible:
        if not (isinstance(entry, dict) and _is_plain_int(entry.get("index"))
                and 0 <= entry["index"] < total):
            return None
        bad.add(entry["index"])
    if len(bad) != len(ineligible):
        return None
    return [i for i in range(total) if i not in bad]


def _filtered_trend_available_in_ok(available_in, name, errors):
    if not (isinstance(available_in, list) and all(_is_plain_int(i) for i in available_in)):
        errors.append("invalid_available_in:%s" % name)
        return False
    if len(set(available_in)) != len(available_in) or available_in != sorted(available_in):
        errors.append("invalid_available_in_ordering:%s" % name)
        return False
    return True


def _filtered_trend_check_availability(name, availability, available_in, eligible_indices,
                                        has_comparisons, errors):
    if availability not in _FILTERED_TREND_AVAILABILITY_STATES:
        errors.append("unknown_trend_availability_state:%s" % name)
        return
    if eligible_indices is None:
        return
    if not all(i in eligible_indices for i in available_in):
        errors.append("available_in_not_eligible:%s" % name)
        return
    flags = [i in set(available_in) for i in eligible_indices]
    if availability != _filtered_trend_availability(flags, has_comparisons):
        errors.append("inconsistent_trend_availability:%s" % name)


def _check_filtered_trend_numeric_entry(field, entry, chronology_ordered, eligible_indices,
                                         has_comparisons, errors):
    name = "numeric.%s" % field
    if not (isinstance(entry, dict) and set(entry.keys()) == set(_FILTERED_TREND_NUMERIC_ENTRY_FIELDS)):
        errors.append("invalid_numeric_trend_entry:%s" % field)
        return
    state = entry["state"]
    if state not in _NUMERIC_TREND_STATES:
        errors.append("unknown_numeric_trend_state:%s" % field)
        return
    available_in = entry["available_in"]
    available_ok = _filtered_trend_available_in_ok(available_in, name, errors)
    _filtered_trend_check_availability(
        name, entry["availability"], available_in if available_ok else [],
        eligible_indices, has_comparisons, errors)

    start, end, delta = entry["start"], entry["end"], entry["delta"]
    if state == TREND_INSUFFICIENT_DATA:
        if start is not None or end is not None or delta is not None:
            errors.append("invalid_insufficient_data_values:%s" % name)
        if available_ok and available_in and chronology_ordered:
            errors.append("inconsistent_insufficient_data:%s" % name)
        return

    if not available_ok or not available_in or chronology_ordered is False:
        errors.append("unsupported_trend_state_without_data:%s" % name)
        return

    is_rate = field in _ANALYSIS_RATE_FIELDS
    values_ok = True
    for role, value in (("start", start), ("end", end)):
        if not _is_finite_number(value) or (not is_rate and not _is_plain_int(value)):
            errors.append("invalid_value_type:%s.%s" % (name, role))
            values_ok = False
    if not _is_finite_number(delta) or (not is_rate and not _is_plain_int(delta)):
        errors.append("invalid_delta_type:%s" % name)
        values_ok = False
    if not values_ok:
        return
    expected_delta = end - start
    correct = (math.isclose(delta, expected_delta, rel_tol=_RATE_TOLERANCE, abs_tol=_RATE_TOLERANCE)
               if is_rate else delta == expected_delta)
    if not correct:
        errors.append("incorrect_trend_delta:%s" % name)
    if state != _numeric_trend_state(start, end):
        errors.append("inconsistent_numeric_trend_state:%s" % field)


def _check_filtered_trend_categorical_entry(name, entry, allowed_states, allowed_change_values,
                                             allowed_start_end_values, allow_appear_disappear,
                                             has_start_end, chronology_ordered, eligible_indices,
                                             has_comparisons, errors):
    expected_fields = (_FILTERED_TREND_REASON_ENTRY_FIELDS if has_start_end
                        else _FILTERED_TREND_COMPOUND_ENTRY_FIELDS)
    if not (isinstance(entry, dict) and set(entry.keys()) == set(expected_fields)):
        errors.append("invalid_categorical_trend_entry:%s" % name)
        return
    state = entry["state"]
    if state not in allowed_states:
        errors.append("unknown_categorical_trend_state:%s" % name)
        return
    available_in = entry["available_in"]
    available_ok = _filtered_trend_available_in_ok(available_in, name, errors)
    _filtered_trend_check_availability(
        name, entry["availability"], available_in if available_ok else [],
        eligible_indices, has_comparisons, errors)

    observed = entry["observed_states"]
    observed_ok = isinstance(observed, list)
    if not observed_ok:
        errors.append("invalid_observed_states:%s" % name)
    else:
        seen_indices = []
        for item in observed:
            if (isinstance(item, dict) and set(item.keys()) == {"index", "change"}
                    and _is_plain_int(item.get("index")) and item.get("change") in allowed_change_values):
                seen_indices.append(item["index"])
            else:
                errors.append("invalid_observed_state_entry:%s" % name)
                observed_ok = False
        if observed_ok and available_ok and seen_indices != available_in:
            errors.append("inconsistent_observed_states:%s" % name)

    if state == TREND_INSUFFICIENT_DATA:
        if has_start_end and (entry.get("start") is not None or entry.get("end") is not None):
            errors.append("invalid_insufficient_data_values:%s" % name)
        if available_ok and available_in and chronology_ordered:
            errors.append("inconsistent_insufficient_data:%s" % name)
        return

    if not available_ok or not available_in or chronology_ordered is False:
        errors.append("unsupported_trend_state_without_data:%s" % name)
        return

    if has_start_end:
        start, end = entry["start"], entry["end"]
        for role, value in (("start", start), ("end", end)):
            if value is not None and value not in allowed_start_end_values:
                errors.append("invalid_trend_value:%s.%s" % (name, role))
                return
        if state != _categorical_trend_state(start, end, allow_appear_disappear):
            errors.append("inconsistent_%s_trend_state" % name)


def _check_filtered_section_availability_entry(section, entry, eligible_indices, has_comparisons, errors):
    name = "section_availability.%s" % section
    if not (isinstance(entry, dict)
            and set(entry.keys()) == set(_FILTERED_TREND_SECTION_AVAILABILITY_FIELDS)):
        errors.append("invalid_section_availability_entry:%s" % section)
        return
    available_in = entry["available_in"]
    available_ok = _filtered_trend_available_in_ok(available_in, name, errors)
    _filtered_trend_check_availability(
        name, entry["availability"], available_in if available_ok else [],
        eligible_indices, has_comparisons, errors)

    presence_counts = entry["presence_counts"]
    counts_ok = (isinstance(presence_counts, dict)
                 and set(presence_counts.keys()) == set(_FILTERED_COMPARISON_PRESENCE_STATES)
                 and all(_is_nonneg_int(v) for v in presence_counts.values()))
    if not counts_ok:
        errors.append("invalid_presence_counts:%s" % name)
        return
    if eligible_indices is not None and sum(presence_counts.values()) != len(eligible_indices):
        errors.append("inconsistent_presence_counts_total:%s" % name)
    if available_ok and presence_counts.get(FILTERED_COMPARISON_PRESENT_BOTH) != len(available_in):
        errors.append("inconsistent_presence_counts_present_both:%s" % name)


def _check_filtered_chronology(chronology, eligible_indices, errors):
    """Returns `chronology["ordered"]` when well-formed enough to trust,
    else `None` (dependent numeric/categorical checks are then skipped
    rather than cascading from an already-reported structural error)."""
    if not (isinstance(chronology, dict) and set(chronology.keys()) == set(_FILTERED_TREND_CHRONOLOGY_FIELDS)):
        errors.append("invalid_chronology")
        return None
    ordered = chronology["ordered"]
    reversed_entries = chronology["reversed"]
    if not _is_bool(ordered):
        errors.append("invalid_chronology_ordered_type")
        return None
    if not isinstance(reversed_entries, list):
        errors.append("invalid_chronology_reversed")
        return None
    entries_ok = True
    for item in reversed_entries:
        if not (isinstance(item, dict) and set(item.keys()) == set(_FILTERED_TREND_REVERSED_ENTRY_FIELDS)
                and _is_plain_int(item.get("index")) and _is_plain_int(item.get("previous_index"))):
            errors.append("invalid_chronology_reversed_entry")
            entries_ok = False
            continue
        if eligible_indices is not None and (item["index"] not in eligible_indices
                                              or item["previous_index"] not in eligible_indices):
            errors.append("invalid_chronology_reversed_index")
    if not entries_ok:
        return None
    if ordered == bool(reversed_entries):
        errors.append("inconsistent_chronology")
    return ordered


def _check_filtered_trend_unavailable(trend_summary, chronology_ordered, errors):
    unavailable = trend_summary.get("unavailable")
    if not _is_list_of_str(unavailable):
        errors.append("invalid_unavailable")
        return
    total = trend_summary.get("total_comparisons")
    eligible = trend_summary.get("eligible_count")
    numeric = trend_summary.get("numeric")
    categorical = trend_summary.get("categorical")
    full_context = (_is_nonneg_int(total) and isinstance(numeric, dict) and isinstance(categorical, dict))
    if not full_context:
        return
    expected = set()
    if total == 0:
        expected.add("no_comparisons")
    elif _is_nonneg_int(eligible) and eligible == 0:
        expected.add("no_eligible_comparisons")
    if chronology_ordered is False:
        expected.add("chronology_not_ordered")
    for field in _TREND_NUMERIC_FIELDS:
        entry = numeric.get(field)
        if isinstance(entry, dict) and entry.get("state") == TREND_INSUFFICIENT_DATA:
            expected.add("insufficient_data:%s" % field)
    for section in _FILTERED_TREND_CATEGORICAL_SECTIONS:
        entry = categorical.get(section)
        if isinstance(entry, dict) and entry.get("state") == TREND_INSUFFICIENT_DATA:
            expected.add("insufficient_data:%s" % section)
    if set(unavailable) != expected:
        errors.append("inconsistent_unavailable_list")


def validate_learned_knowledge_filtered_summary_snapshot_comparison_trend(
        trend_summary, comparisons=_NOT_PROVIDED):
    """Deterministic, read-only validation of `trend_summary` - the dict
    `summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend()`
    (Prompt 520) returns. Returns a new, independent dict in the same
    `{"valid", "well_formed", "errors", "warnings"}` style as the Prompt
    506/510/512/519 validators.

    `valid` is `True` exactly when `errors` is empty. `well_formed` is
    `False` when the summary is malformed or internally inconsistent on
    its own (missing/malformed fields, contradictory counts, an
    `"availability"` that does not match its own `"available_in"`, a
    trend `"state"` that does not match its own `"start"`/`"end"`, a
    `"chronology"` block that contradicts itself, a `"section_availability"`
    or `"unavailable"` entry that contradicts the rest of the summary).
    A summary can be well-formed yet not fully valid when `comparisons`
    (the same ordered collection it claims to summarize) is given and
    does not match what recomputing the trend from it actually produces
    (`"mismatched_field:.."` / `"mismatched_numeric:<field>"` /
    `"mismatched_categorical:<section>"`).

    A composite categorical section (`comparison_changes`, `trend`,
    `validation_statuses`) keeps no scalar value in the trend entry
    itself, so its `"state"` can only be fully checked against real data
    when `comparisons` is supplied; without it, only its shape and
    `"insufficient_data"` consistency are checked.

    Never repairs, regenerates for any purpose other than the optional
    comparison, or otherwise changes `trend_summary` or `comparisons`; a
    non-dict `trend_summary` safely yields `"trend_summary_not_a_dict"`.
    Not called anywhere in the gate/decision/response path; it does not
    interpret a trend as good or bad, rank it, or predict anything from
    it. Deterministic: the same inputs always give an equal result.
    """
    structural = []
    source_errors = []

    if not isinstance(trend_summary, dict):
        structural.append("trend_summary_not_a_dict")
        errors = structural + source_errors
        return {"valid": not errors, "well_formed": not structural, "errors": errors, "warnings": []}

    for field in _FILTERED_TREND_REQUIRED_FIELDS:
        if field not in trend_summary:
            structural.append("missing_field:%s" % field)

    if "valid" in trend_summary and trend_summary["valid"] is not True:
        structural.append("invalid_trend_valid_value")
    if "errors" in trend_summary and trend_summary["errors"] != []:
        structural.append("invalid_trend_errors_value")
    if "direction" in trend_summary and trend_summary["direction"] != COMPARISON_DIRECTION:
        structural.append("invalid_direction")

    counts_ok = True
    for field in ("total_comparisons", "eligible_count", "ineligible_count"):
        if field in trend_summary and not _is_nonneg_int(trend_summary[field]):
            structural.append("invalid_type:%s" % field)
            counts_ok = False

    total_comparisons = trend_summary.get("total_comparisons")
    eligible_count = trend_summary.get("eligible_count")
    ineligible_count = trend_summary.get("ineligible_count")
    all_counts_present = all(
        field in trend_summary for field in ("total_comparisons", "eligible_count", "ineligible_count"))

    if counts_ok and all_counts_present and eligible_count + ineligible_count != total_comparisons:
        structural.append("inconsistent_comparison_counts")

    bound = total_comparisons if _is_nonneg_int(total_comparisons) else None
    if "ineligible_comparisons" in trend_summary:
        ineligible = trend_summary["ineligible_comparisons"]
        if isinstance(ineligible, list):
            if _is_nonneg_int(ineligible_count) and len(ineligible) != ineligible_count:
                structural.append("inconsistent_ineligible_count")
            _check_ineligible_comparisons(ineligible, bound, structural)
        else:
            structural.append("invalid_ineligible_comparisons")

    eligible_indices = _filtered_trend_eligible_indices(trend_summary)
    if (eligible_indices is not None and _is_nonneg_int(eligible_count)
            and len(eligible_indices) != eligible_count):
        structural.append("inconsistent_eligible_count")
    has_comparisons = (total_comparisons > 0) if eligible_indices is not None else None

    if "chronological_range" in trend_summary:
        _check_trend_chronological_range(
            trend_summary["chronological_range"],
            eligible_count if _is_nonneg_int(eligible_count) else None,
            structural,
        )

    chronology_ordered = None
    if "chronology" in trend_summary:
        chronology_ordered = _check_filtered_chronology(trend_summary["chronology"], eligible_indices, structural)

    if "numeric" in trend_summary:
        numeric = trend_summary["numeric"]
        if not isinstance(numeric, dict):
            structural.append("invalid_numeric")
        else:
            for field in _TREND_NUMERIC_FIELDS:
                if field not in numeric:
                    structural.append("missing_numeric_trend_field:%s" % field)
                else:
                    _check_filtered_trend_numeric_entry(
                        field, numeric[field], chronology_ordered, eligible_indices,
                        has_comparisons, structural)

    if "categorical" in trend_summary:
        categorical = trend_summary["categorical"]
        if not isinstance(categorical, dict):
            structural.append("invalid_categorical")
        else:
            for section in _FILTERED_TREND_CATEGORICAL_SECTIONS:
                if section not in categorical:
                    structural.append("missing_categorical_trend_field:%s" % section)
                    continue
                reason = section == "dominant_rejection_reason"
                allowed_states = _DOMINANT_REASON_TREND_STATES if reason else _VALIDATION_STATUS_TREND_STATES
                allowed_change_values = _FILTERED_REASON_STATES if reason else _FILTERED_COMPOUND_STATES
                allowed_start_end_values = _REJECTION_DECISIONS if reason else ()
                _check_filtered_trend_categorical_entry(
                    section, categorical[section], allowed_states, allowed_change_values,
                    allowed_start_end_values, reason, reason, chronology_ordered, eligible_indices,
                    has_comparisons, structural)

    if "section_availability" in trend_summary:
        section_availability = trend_summary["section_availability"]
        if not isinstance(section_availability, dict):
            structural.append("invalid_section_availability")
        else:
            for section in _SUMMARY_SECTIONS:
                if section not in section_availability:
                    structural.append("missing_section_availability_field:%s" % section)
                else:
                    _check_filtered_section_availability_entry(
                        section, section_availability[section], eligible_indices, has_comparisons, structural)

    if "validation_status" in trend_summary:
        _check_trend_categorical_entry(
            "validation_status", trend_summary["validation_status"],
            _VALIDATION_STATUS_TREND_STATES, _SNAPSHOT_STATUSES, False, False, structural)

    if "unavailable" in trend_summary:
        _check_filtered_trend_unavailable(trend_summary, chronology_ordered, structural)

    # --- optional cross-check against the actual source comparisons --------
    if comparisons is not _NOT_PROVIDED:
        expected = summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend(comparisons)
        for field in ("total_comparisons", "eligible_count", "ineligible_count",
                      "ineligible_comparisons", "chronological_range", "chronology",
                      "section_availability", "validation_status", "unavailable"):
            if trend_summary.get(field) != expected.get(field):
                source_errors.append("mismatched_field:%s" % field)
        numeric = trend_summary.get("numeric")
        if isinstance(numeric, dict):
            for field in _TREND_NUMERIC_FIELDS:
                if numeric.get(field) != expected["numeric"][field]:
                    source_errors.append("mismatched_numeric:%s" % field)
        categorical = trend_summary.get("categorical")
        if isinstance(categorical, dict):
            for section in _FILTERED_TREND_CATEGORICAL_SECTIONS:
                if categorical.get(section) != expected["categorical"][section]:
                    source_errors.append("mismatched_categorical:%s" % section)

    errors = structural + source_errors
    return {"valid": not errors, "well_formed": not structural, "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 536 - consistency between filtered comparisons and the filtered
# trend summary that claims to summarize them
# ----------------------------------------------------------------------
# `validate_learned_knowledge_filtered_summary_snapshot_comparison_trend()`
# (Prompt 521, above) already accepts an optional `comparisons` argument
# and, when given it, flags any disagreement with a handful of broad
# `"mismatched_field:.."` / `"mismatched_numeric:.."` / `"mismatched_
# categorical:.."` codes covering the whole trend summary at once. That
# behavior is unchanged here.
#
# `validate_learned_knowledge_filtered_comparison_trend_consistency()`
# reuses the same two existing systems - the Prompt 520 summarizer
# (`summarize_learned_knowledge_filtered_summary_snapshot_comparison_
# trend`, to recompute what `comparisons` actually produces) and the
# Prompt 521 validator (for `trend_summary`'s own internal well-
# formedness) - together with the existing Prompt 528 per-entry
# comparator (`_check_trend_against_source_comparisons`, already used at
# the whole-report level for exactly this purpose) to report *which*
# specific disagreement exists, not just that one does:
#
#   - `"invalid_source:comparisons"` - `comparisons` is neither a list,
#     a tuple, nor `None`.
#   - `"inconsistent_comparison_count:filtered_trend.<field>"` - a
#     declared `total_comparisons` / `eligible_count` / `ineligible_
#     count` does not match how many of `comparisons` are actually
#     eligible.
#   - `"trend_entry_without_comparison:filtered_trend.<path>.<index>"` -
#     a trend entry names an index outside `comparisons` altogether.
#   - `"extra_trend_entry:filtered_trend.<path>.<index>"` - a trend
#     entry names a comparison that exists but is not eligible.
#   - `"missing_trend_entry:filtered_trend.<path>.<index>"` - an
#     eligible comparison that no trend entry accounts for.
#   - `"inconsistent_numeric_trend_state:filtered_trend.<field>"` /
#     `"inconsistent_categorical_trend_state:filtered_trend.<section>"` -
#     a trend entry's own `"state"` does not match what `comparisons`
#     actually shows for it.
#
# Prompt 537 adds one more targeted comparison on top of the above: the
# declared `"chronology"` block against what recomputing from the real
# `comparisons` actually shows. A chronology disagreement does not
# always surface as a numeric/categorical state mismatch - a trend
# whose fields all read `"insufficient_data"` either way, or a
# `"reversed"` entry that names the wrong pair of positions while the
# `"ordered"` flag still happens to agree, would otherwise pass. This
# reuses the same recomputed `expected` this function already builds
# (via the Prompt 520 summarizer) rather than deriving chronology
# again, and adds:
#
#   - `"inconsistent_trend_chronology:filtered_trend.chronology.ordered"` -
#     the declared `chronology.ordered` does not match whether the
#     eligible `comparisons` are actually in chronological order.
#   - `"inconsistent_trend_chronology:filtered_trend.chronology.reversed"` -
#     the declared `chronology.reversed` entries (which eligible
#     comparison position reads as going backwards, and relative to
#     which earlier one) do not match what `comparisons` actually
#     shows, including a reversed entry naming the wrong pair, a
#     missing one, or an extra one - covering reversed ordering,
#     duplicated chronological positions, and any other conflicting
#     position the recomputed chronology disagrees with.
#
# An empty or single-comparison trend is handled like any other case,
# not a special case: with zero or one eligible comparison there is
# nothing to be out of order, so both the declared and recomputed
# `chronology` are trivially `{"ordered": True, "reversed": []}` and
# agree. Reused verbatim from Prompt 520's own chronology computation
# (`_filtered_trend_chronology`) - no new ordering logic, metric, or
# analysis is introduced, and neither `trend_summary` nor `comparisons`
# is ever reordered, repaired, or otherwise changed.
#
# A `trend_summary` that is not well-formed on its own is reported as
# such (its own Prompt 521 errors are carried through unchanged) and is
# not further cross-checked against `comparisons` - the same "leave a
# malformed payload to its own validator" rule the rest of this module
# follows. Empty `comparisons` and a `trend_summary` with zero eligible
# comparisons are handled like any other input, not a special case that
# raises or is skipped.
#
# Creates no metric, prediction, score, or recommendation of its own;
# never repairs, regenerates, reorders, or otherwise changes
# `trend_summary` or `comparisons`. Not called from the gate/decision/
# response path. Deterministic: the same inputs always give an equal
# result.


def _reversed_entries_well_formed(reversed_entries):
    """Whether `reversed_entries` is a list of `{"index", "previous_index"}`
    int-valued dicts - the shape Prompt 521's own structural check
    already requires before trusting it for comparison here."""
    return isinstance(reversed_entries, list) and all(
        isinstance(item, dict) and _is_plain_int(item.get("index"))
        and _is_plain_int(item.get("previous_index")) for item in reversed_entries)


def _check_filtered_trend_chronology_against_comparisons(name, summary, expected, errors):
    """Prompt 537: `summary`'s declared `"chronology"` against `expected`
    - what the Prompt 520 summarizer actually recomputes from the real
    source comparisons. Compared exactly (not just as a set of pairs) so
    a reversed entry naming the wrong position, a duplicated entry, or an
    extra/missing one are all caught, on top of a plain reversed-vs-
    ordered disagreement. Read-only and additive: reports a
    disagreement, never corrects or reorders anything. A missing/
    malformed `chronology` on either side is left to the existing
    structural checks (Prompt 521's `_check_filtered_chronology`); this
    only compares two blocks already known to be well-formed enough to
    read."""
    if not isinstance(summary, dict) or not isinstance(expected, dict):
        return
    chronology, wanted = summary.get("chronology"), expected.get("chronology")
    if not (isinstance(chronology, dict) and isinstance(wanted, dict)):
        return
    path = "%s.chronology" % name

    ordered, wanted_ordered = chronology.get("ordered"), wanted.get("ordered")
    if _is_bool(ordered) and _is_bool(wanted_ordered) and ordered != wanted_ordered:
        _add_error(errors, "inconsistent_trend_chronology:%s.ordered" % path)

    reported_reversed, wanted_reversed = chronology.get("reversed"), wanted.get("reversed")
    if (_reversed_entries_well_formed(reported_reversed) and _reversed_entries_well_formed(wanted_reversed)
            and reported_reversed != wanted_reversed):
        _add_error(errors, "inconsistent_trend_chronology:%s.reversed" % path)


def validate_learned_knowledge_filtered_comparison_trend_consistency(comparisons, trend_summary):
    """Deterministic, read-only check of whether `trend_summary` - a dict
    in the shape `summarize_learned_knowledge_filtered_summary_snapshot_
    comparison_trend()` (Prompt 520) returns - is consistent with
    `comparisons`, the ordered filtered-comparison collection (Prompt
    519 `compare_learned_knowledge_filtered_summary_snapshots()` results)
    it claims to summarize.

    Returns the usual `{"valid", "well_formed", "errors", "warnings"}`
    shape. `well_formed` reflects only `trend_summary`'s own internal
    consistency, exactly as `validate_learned_knowledge_filtered_summary_
    snapshot_comparison_trend()` (Prompt 521) reports it. `valid`
    additionally requires `comparisons` to be a list/tuple (or `None`,
    treated as empty) and every trend entry to correspond to what
    `comparisons` actually produces - see the module note above for the
    exact set of codes this can add.

    Never repairs, regenerates, or otherwise changes either argument;
    assigns no score, rank, or prediction. Deterministic: the same
    inputs always give an equal result.
    """
    base = validate_learned_knowledge_filtered_summary_snapshot_comparison_trend(trend_summary)
    errors = list(base["errors"])

    if comparisons is None or isinstance(comparisons, (list, tuple)):
        if base["well_formed"]:
            listed = list(comparisons) if comparisons else []
            expected = summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend(listed)
            _check_trend_against_source_comparisons(
                "filtered_trend", trend_summary, expected, len(listed), True, errors)
            _check_filtered_trend_chronology_against_comparisons(
                "filtered_trend", trend_summary, expected, errors)
    else:
        errors.append("invalid_source:comparisons")

    return {"valid": not errors, "well_formed": base["well_formed"], "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 538 - source integrity of a Prompt 520 filtered diagnostic trend
# ----------------------------------------------------------------------
# `validate_learned_knowledge_filtered_comparison_trend_consistency()`
# (Prompt 536/537) checks that a filtered trend summary's own declared
# counts, entries, and chronology agree with recomputing the trend from
# `comparisons`. That already catches a comparison the trend treats as
# eligible when the real data disagrees (it shows up as an
# `"extra_trend_entry"` / `"missing_trend_entry"` / count mismatch,
# because the Prompt 520 summarizer used to build `expected` judges
# every comparison with the Prompt 519 validator itself). What it does
# not do is name, in one place, exactly *why* a comparison the trend
# relies on is unusable - missing, malformed, or independently invalid -
# or flag plainly that the trend was left reading as valid despite it.
#
# `validate_learned_knowledge_filtered_trend_source_integrity()` adds
# exactly that, reusing the existing systems rather than duplicating
# them: the Prompt 536/537 consistency check (called first, unchanged,
# for the base envelope and every code it already reports) and the
# Prompt 519 comparison validator
# (`validate_learned_knowledge_filtered_summary_snapshot_comparison`,
# called on each comparison the trend claims is eligible - reusing the
# existing `_filtered_trend_eligible_indices()` helper to read which
# positions those are directly off the trend's own declared fields, the
# same way Prompt 521's own structural checks already do). Only
# positions the trend actually relies on are checked this way: a
# comparison the trend already lists as ineligible is expected to
# possibly be missing, malformed, or invalid, and needs no source-
# integrity error of its own - that case is exactly what "ineligible"
# means.
#
# For every eligible position, in order:
#   - `"missing_source_comparison:filtered_trend.<index>"` - `comparisons`
#     has nothing at that position (too short, or an explicit `None`).
#   - `"malformed_source_comparison:filtered_trend.<index>"` - what is
#     there is not a dict, or is a dict the Prompt 519 validator itself
#     cannot make sense of structurally (`well_formed` is `False`).
#   - `"invalid_source_comparison:filtered_trend.<index>"` - a
#     structurally well-formed comparison that the Prompt 519 validator
#     itself reports as not valid.
#   - `"trend_marked_valid_with_invalid_source:filtered_trend.<index>"` -
#     added alongside any of the three codes above whenever the trend
#     summary's own declared `"valid"` is `True` regardless: a trend
#     reading as valid is understood as one whose sources are all
#     usable, so an unusable eligible source and a `True` `"valid"`
#     flag are reported as the specific disagreement they are, not just
#     folded into the generic consistency codes above.
#
# `well_formed` is exactly the base consistency check's `well_formed` -
# source integrity is a `valid`-level concern only, and (like the rest
# of this module) a `trend_summary` that is not well-formed on its own
# is left to its own structural errors rather than cross-checked
# further; the eligible positions can only be trusted once the trend's
# own `total_comparisons` / `ineligible_comparisons` fields are known to
# be internally consistent. `comparisons` given as anything other than
# a list, a tuple, or `None` is reported exactly as the base check
# reports it (`"invalid_source:comparisons"`), with no per-position
# checks attempted. An empty trend (no comparisons at all) or one with
# zero eligible comparisons needs no special case - there is simply
# nothing to check per position, the same as any other input.
#
# Creates no metric, prediction, score, or recommendation of its own;
# never repairs, regenerates, reorders, or otherwise changes
# `trend_summary` or any comparison in `comparisons`. Not called from
# the gate/decision/response path. Deterministic: the same inputs
# always give an equal result.


def _filtered_source_comparison_problem(comparison):
    """Prompt 538: what is wrong, if anything, with a single source
    comparison taken on its own - `None` when it is a well-formed,
    independently valid Prompt 518 comparison. Reuses the existing
    Prompt 519 validator rather than re-checking comparison shape
    itself; never repairs or regenerates anything."""
    if comparison is None:
        return "missing_source_comparison"
    if not isinstance(comparison, dict):
        return "malformed_source_comparison"
    result = validate_learned_knowledge_filtered_summary_snapshot_comparison(comparison)
    if not result["well_formed"]:
        return "malformed_source_comparison"
    if not result["valid"]:
        return "invalid_source_comparison"
    return None


def validate_learned_knowledge_filtered_trend_source_integrity(comparisons, trend_summary):
    """Deterministic, read-only check of whether every source comparison
    `trend_summary` - a dict in the shape `summarize_learned_knowledge_
    filtered_summary_snapshot_comparison_trend()` (Prompt 520) returns -
    actually relies on (its eligible positions) exists and is
    independently valid, on top of the existing Prompt 536/537
    consistency check between `trend_summary` and `comparisons`.

    Returns the usual `{"valid", "well_formed", "errors", "warnings"}`
    shape. `well_formed` is exactly `validate_learned_knowledge_
    filtered_comparison_trend_consistency()`'s own `well_formed` (the
    trend summary's Prompt 521 internal consistency); source integrity
    adds no new notion of well-formedness. `valid` additionally requires
    every position `trend_summary` itself declares eligible (derived
    from its own `total_comparisons` / `ineligible_comparisons` fields)
    to exist in `comparisons` and be independently valid under the
    existing Prompt 519 validator - see the module note above for the
    exact codes this can add, including the dedicated code for a trend
    that reads `"valid\": True` despite one of those sources being
    unusable.

    `comparisons` given as anything other than a list, a tuple, or
    `None` is reported exactly as the base consistency check reports it.
    An empty trend or one with zero eligible comparisons is handled like
    any other input, not a special case.

    Never repairs, regenerates, or otherwise changes `trend_summary` or
    `comparisons`; assigns no score, rank, or prediction. Deterministic:
    the same inputs always give an equal result.
    """
    base = validate_learned_knowledge_filtered_comparison_trend_consistency(comparisons, trend_summary)
    errors = list(base["errors"])

    if comparisons is None or isinstance(comparisons, (list, tuple)):
        if base["well_formed"]:
            listed = list(comparisons) if comparisons else []
            eligible_indices = _filtered_trend_eligible_indices(trend_summary)
            trend_valid = trend_summary.get("valid") is True
            if eligible_indices is not None:
                for index in eligible_indices:
                    comparison = listed[index] if 0 <= index < len(listed) else None
                    problem = _filtered_source_comparison_problem(comparison)
                    if problem is None:
                        continue
                    _add_error(errors, "%s:filtered_trend.%d" % (problem, index))
                    if trend_valid:
                        _add_error(
                            errors, "trend_marked_valid_with_invalid_source:filtered_trend.%d" % index)
    # else: an invalid `comparisons` type is already reported by `base`
    # ("invalid_source:comparisons"); no per-position check is possible.

    return {"valid": not errors, "well_formed": base["well_formed"], "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 539 - validate filtered trend source references
# ----------------------------------------------------------------------
# `validate_learned_knowledge_filtered_trend_source_integrity()` (Prompt
# 538, above) already reuses the Prompt 536/537 consistency check and the
# Prompt 519 comparison validator to name, per eligible position, exactly
# why a relied-on source comparison is unusable (missing, malformed, or
# invalid), plus whether the trend still reads `"valid": True` despite
# it. Together with what it already builds on, that covers five of the
# nine reference problems this prompt asks a validator to detect:
#   - missing source comparison references / references to a position
#     that does not exist in `comparisons` at all -> both already surface
#     as `"missing_source_comparison:filtered_trend.<index>"` (Prompt 538
#     does not distinguish an explicit `None` from an out-of-range index;
#     either way there is nothing usable there).
#   - invalid comparison objects -> `"malformed_source_comparison:.."` /
#     `"invalid_source_comparison:.."` (Prompt 538).
#   - mismatched comparison count -> `"inconsistent_comparison_count:.."`
#     (Prompt 536, in the base consistency check).
#   - mismatched comparison ordering -> `"inconsistent_trend_chronology:.."`
#     (Prompt 537, in the base consistency check).
#
# What is genuinely new here is checking the *relationships between* the
# source comparisons a trend relies on - not just whether each one is
# independently present and valid, but whether, taken together in the
# trend's own eligible order, they actually form one connected chain of
# adjacent snapshot comparisons (exactly the shape every real filtered
# trend is built from: comparison i's `"later"` snapshot is comparison
# i + 1's `"earlier"` snapshot). `validate_learned_knowledge_filtered_
# trend_source_references()` adds four new, targeted checks on top of
# the Prompt 538 result (called first, unchanged) - reusing its own
# per-position problem check (`_filtered_source_comparison_problem`) to
# decide which eligible positions are clean enough to read `"earlier"`/
# `"later"` from safely, so a position Prompt 538 already flagged is
# never also given one of these new, additive codes:
#
#   - `"duplicated_source_reference:filtered_trend.<index>"` - this
#     position's `("earlier".snapshot_id, "later".snapshot_id)` pair is
#     identical to an already-seen eligible position's pair (the same
#     underlying source comparison relied on twice).
#   - `"unrelated_source_reference:filtered_trend.<index>"` - this
#     position's `"earlier".snapshot_id` does not match the previous
#     clean eligible position's `"later".snapshot_id`: the chain is
#     broken by a comparison that is not a continuation of the one
#     before it.
#   - `"inconsistent_earlier_later_relationship:filtered_trend.<index>"` -
#     the previous clean eligible position's `"later"` and this
#     position's `"earlier"` name the SAME snapshot id yet disagree on
#     its `"sequence"` - the two comparisons agree on identity but
#     contradict each other about where that snapshot sits.
#   - `"inconsistent_source_id:filtered_trend.<index>"` - a snapshot id
#     seen anywhere earlier among the clean eligible positions (as
#     either `"earlier"` or `"later"`) reappears here with a different
#     `"sequence"` than it was first seen with - a broader identity/
#     sequence contradiction, not limited to adjacent positions.
#
# Only the clean eligible positions (no Prompt 538 problem) are compared
# against each other, and only in the trend's own ascending eligible
# order - the exact order `_filtered_trend_eligible_indices()` already
# returns. A position Prompt 538 already flagged contributes nothing to
# these checks and is simply skipped when looking for "the previous
# clean position", so a single unusable source never cascades into a
# spurious "unrelated"/"inconsistent" report about its neighbors.
#
# `well_formed` is exactly the base result's `well_formed` (Prompt 538's
# own, itself Prompt 536/537's) - these are `valid`-level checks only.
# `comparisons` given as anything other than a list, a tuple, or `None`
# is reported exactly as the base result reports it, with no reference
# checks attempted. An empty trend, one with zero eligible comparisons,
# or a single eligible comparison is handled like any other input: with
# fewer than two clean eligible positions there is nothing to compare,
# so none of the four new codes can ever fire.
#
# Reuses the existing filtered trend, filtered comparison, and
# validation structures throughout; creates no second trend or
# comparison system, no metric, prediction, score, rank, or
# recommendation. Never repairs, regenerates, reorders, or otherwise
# changes `trend_summary` or any comparison in `comparisons`. Not called
# from the gate/decision/response path. Deterministic: the same inputs
# always give an equal result.


def _filtered_source_reference_identity(comparison, role):
    """The `{"snapshot_id", "sequence"}` identity `comparison[role]`
    records - only ever called on a comparison already known (via
    `_filtered_source_comparison_problem`) to be a well-formed, valid
    Prompt 518 comparison, so the field is always present and shaped
    that way."""
    return comparison[role]


def validate_learned_knowledge_filtered_trend_source_references(comparisons, trend_summary):
    """Deterministic, read-only check of whether the source comparisons
    `trend_summary` - a dict in the shape `summarize_learned_knowledge_
    filtered_summary_snapshot_comparison_trend()` (Prompt 520) returns -
    relies on (its eligible positions) form one connected, internally
    consistent chain within `comparisons`, on top of the existing Prompt
    536/537/538 checks.

    Returns the usual `{"valid", "well_formed", "errors", "warnings"}`
    shape. `well_formed` is exactly `validate_learned_knowledge_
    filtered_trend_source_integrity()`'s own `well_formed`; these
    reference checks add no new notion of well-formedness. `valid`
    additionally requires the eligible positions that are independently
    present and valid to agree with each other on the identity and
    sequence of the snapshots they share - see the module note above for
    the exact codes this can add: `"duplicated_source_reference:.."`,
    `"unrelated_source_reference:.."`, `"inconsistent_earlier_later_
    relationship:.."`, and `"inconsistent_source_id:.."`.

    `comparisons` given as anything other than a list, a tuple, or
    `None` is reported exactly as the base check reports it. An empty
    trend, one with zero eligible comparisons, or a single eligible
    comparison is handled like any other input - there is nothing to
    compare with fewer than two clean eligible positions.

    Never repairs, regenerates, or otherwise changes `trend_summary` or
    `comparisons`; assigns no score, rank, or prediction. Deterministic:
    the same inputs always give an equal result.
    """
    base = validate_learned_knowledge_filtered_trend_source_integrity(comparisons, trend_summary)
    errors = list(base["errors"])

    if comparisons is None or isinstance(comparisons, (list, tuple)):
        if base["well_formed"]:
            listed = list(comparisons) if comparisons else []
            eligible_indices = _filtered_trend_eligible_indices(trend_summary)
            if eligible_indices is not None:
                clean = []
                for index in eligible_indices:
                    comparison = listed[index] if 0 <= index < len(listed) else None
                    if _filtered_source_comparison_problem(comparison) is None:
                        clean.append((index, comparison))

                seen_pairs = set()
                known_sequence_by_id = {}
                previous = None
                for index, comparison in clean:
                    earlier = _filtered_source_reference_identity(comparison, "earlier")
                    later = _filtered_source_reference_identity(comparison, "later")

                    pair = (earlier["snapshot_id"], later["snapshot_id"])
                    if pair in seen_pairs:
                        _add_error(errors, "duplicated_source_reference:filtered_trend.%d" % index)
                    seen_pairs.add(pair)

                    if previous is not None:
                        previous_later = _filtered_source_reference_identity(previous[1], "later")
                        if previous_later["snapshot_id"] != earlier["snapshot_id"]:
                            _add_error(errors, "unrelated_source_reference:filtered_trend.%d" % index)
                        elif previous_later["sequence"] != earlier["sequence"]:
                            _add_error(
                                errors,
                                "inconsistent_earlier_later_relationship:filtered_trend.%d" % index)

                    for identity in (earlier, later):
                        snapshot_id, sequence = identity["snapshot_id"], identity["sequence"]
                        if snapshot_id in known_sequence_by_id:
                            if known_sequence_by_id[snapshot_id] != sequence:
                                _add_error(errors, "inconsistent_source_id:filtered_trend.%d" % index)
                        else:
                            known_sequence_by_id[snapshot_id] = sequence

                    previous = (index, comparison)
    # else: an invalid `comparisons` type is already reported by `base`
    # ("invalid_source:comparisons"); no per-position check is possible.

    return {"valid": not errors, "well_formed": base["well_formed"], "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 540 - validate filtered trend source consistency
# ----------------------------------------------------------------------
# `validate_learned_knowledge_filtered_trend_source_references()`
# (Prompt 539, above) already detects every way a filtered diagnostic
# trend's eligible source comparisons can disagree with `comparisons`:
# missing, malformed, or independently invalid sources (Prompt 538); an
# eligible-count or chronology mismatch against what recomputing the
# trend actually produces (Prompt 536/537); and, among the eligible
# positions that are themselves clean, a duplicated reference, a broken
# chain link to an unrelated comparison, or a contradicted snapshot
# identity/sequence (Prompt 539's own four checks). Nothing here adds a
# new way for a filtered trend and its source comparisons to disagree.
#
# What this prompt adds is a small, read-only summarization layer over
# that existing detection: a deterministic, per-eligible-position
# consistency category - reusing the Prompt 539 result's own `errors`
# entries to decide each category rather than re-deriving anything - so
# a caller can see, at a glance, per index, which of a small fixed set
# of problem kinds (if any) applies, instead of having to parse error
# code prefixes itself. `validate_learned_knowledge_filtered_trend_
# source_consistency()` calls Prompt 539 first, unchanged, for the full
# envelope ("valid", "well_formed", "errors", "warnings"), and adds two
# read-only fields on top:
#
#   - "status" - exactly "valid" when the Prompt 539 result's own
#     "valid" is True, else "invalid". A plain restatement of the
#     existing boolean as one of the two overall status words this
#     prompt asks for, nothing more.
#   - "sources" - a {index: category} mapping with exactly one entry
#     for every position `trend_summary` itself declares eligible (via
#     the same `_filtered_trend_eligible_indices()` helper Prompt
#     538/539 already use) - so no eligible position is ever silently
#     left out of the breakdown - each mapped to exactly one of:
#       "valid"             - no Prompt 538/539 problem at this position.
#       "missing"           - `comparisons` has nothing at this position
#                             (Prompt 538's missing_source_comparison).
#       "invalid_source"    - what is there is malformed or
#                             independently invalid (Prompt 538's
#                             malformed_source_comparison /
#                             invalid_source_comparison).
#       "duplicated"        - this position reuses another eligible
#                             position's exact source (Prompt 539's
#                             duplicated_source_reference).
#       "ordering_mismatch" - this position's source does not continue
#                             the chain the previous clean eligible
#                             position left off at (Prompt 539's
#                             unrelated_source_reference).
#       "mismatched"        - the sources agree on the chain link but
#                             contradict each other, or an earlier
#                             position, about a shared snapshot's
#                             identity (Prompt 539's inconsistent_
#                             source_id / inconsistent_earlier_later_
#                             relationship).
#     Only one category is reported per position: by construction, the
#     Prompt 538 checks (missing/malformed/invalid) are attempted first
#     and, when any of them applies, are the only thing that can apply
#     (Prompt 539 only compares positions Prompt 538 already found
#     clean against each other) - so the two never overlap for the same
#     index, and the four Prompt 539 checks are themselves mutually
#     exclusive for a given position by the same reasoning Prompt 539
#     already documents.
#
# A count mismatch or a reversed/inconsistent chronology is a whole-
# trend disagreement, not tied to any single eligible position; it
# remains exactly what it always was, a "valid": False result with the
# matching code ("inconsistent_comparison_count:..",
# "inconsistent_trend_chronology:..") in "errors", unchanged from
# Prompt 536 - "sources" is still populated per the trend's own
# declared eligible positions (each categorized off `comparisons` as it
# actually was given), since that per-position detail remains as
# meaningful as ever even when the whole-trend counts disagree. Only an
# invalid `comparisons` type, or a `trend_summary` that is not itself
# well-formed, leaves "sources" as {} - exactly the same gating Prompt
# 538/539 already use before deriving eligible indices - with the
# reason already visible in "errors"/"well_formed".
#
# `well_formed` is exactly the Prompt 539 result's own `well_formed`;
# this prompt adds no new notion of well-formedness. An empty trend, a
# trend with zero eligible comparisons, or one with a single eligible
# comparison is handled like any other input - "sources" is simply {}
# or has one "valid" entry, and the overall result reads "valid" /
# "status": "valid", exactly as Prompt 536/538/539 already treat these
# cases.
#
# Reuses the existing filtered trend, filtered comparison, and
# validation structures throughout; creates no second trend or
# comparison system, no metric, prediction, score, rank, or
# recommendation. Never repairs, regenerates, reorders, or otherwise
# changes `trend_summary` or any comparison in `comparisons`. Not called
# from the gate/decision/response path. Deterministic: the same inputs
# always give an equal result.


_FILTERED_TREND_SOURCE_CONSISTENCY_CATEGORIES = (
    "valid", "missing", "invalid_source", "duplicated", "ordering_mismatch", "mismatched",
)


def _filtered_trend_source_consistency_category(index, base_errors):
    """The Prompt 540 consistency category for one eligible trend
    position - exactly one of `_FILTERED_TREND_SOURCE_CONSISTENCY_
    CATEGORIES` - derived entirely by looking for the already-computed
    Prompt 538/539 error codes for this position in `base_errors`; adds
    no new detection logic of its own. See the module note above for
    why at most one of these can ever match a given position."""
    suffix = ":filtered_trend.%d" % index
    for code, category in (
            ("missing_source_comparison", "missing"),
            ("malformed_source_comparison", "invalid_source"),
            ("invalid_source_comparison", "invalid_source"),
            ("duplicated_source_reference", "duplicated"),
            ("unrelated_source_reference", "ordering_mismatch"),
            ("inconsistent_source_id", "mismatched"),
            ("inconsistent_earlier_later_relationship", "mismatched")):
        if (code + suffix) in base_errors:
            return category
    return "valid"


def validate_learned_knowledge_filtered_trend_source_consistency(comparisons, trend_summary):
    """Deterministic, read-only summarization of whether the source
    comparisons `trend_summary` - a dict in the shape `summarize_
    learned_knowledge_filtered_summary_snapshot_comparison_trend()`
    (Prompt 520) returns - relies on (its eligible positions) are
    consistent with `comparisons`, on top of the existing Prompt
    536/537/538/539 checks.

    Returns {"valid", "well_formed", "errors", "warnings"} exactly as
    `validate_learned_knowledge_filtered_trend_source_references()`
    (Prompt 539) reports them - this prompt adds no new detection - plus
    two additional, read-only fields: "status" ("valid" or "invalid", a
    restatement of "valid") and "sources", a {index: category} mapping
    with one entry for every position `trend_summary` declares
    eligible, each categorized as "valid", "missing", "invalid_source",
    "duplicated", "ordering_mismatch", or "mismatched" - see the module
    note above for what each category means and exactly how it is
    derived from the existing Prompt 538/539 error codes.

    `comparisons` given as anything other than a list, a tuple, or
    `None`, or a `trend_summary` that is not well-formed, is reported
    exactly as the Prompt 539 result reports it, with "sources" left
    empty - no per-position categorization is attempted. An empty
    trend, a trend with zero eligible comparisons, or one with a single
    eligible comparison is handled like any other input.

    Never repairs, regenerates, or otherwise changes `trend_summary` or
    `comparisons`; assigns no score, rank, or prediction. Deterministic:
    the same inputs always give an equal result.
    """
    base = validate_learned_knowledge_filtered_trend_source_references(comparisons, trend_summary)
    errors = list(base["errors"])
    sources = {}

    if base["well_formed"] and (comparisons is None or isinstance(comparisons, (list, tuple))):
        eligible_indices = _filtered_trend_eligible_indices(trend_summary)
        if eligible_indices is not None:
            for index in eligible_indices:
                sources[index] = _filtered_trend_source_consistency_category(index, errors)

    return {
        "valid": base["valid"],
        "well_formed": base["well_formed"],
        "status": "valid" if base["valid"] else "invalid",
        "errors": errors,
        "warnings": [],
        "sources": sources,
    }


# ----------------------------------------------------------------------
# Prompt 541 - validate filtered trend source coverage
# ----------------------------------------------------------------------
# `validate_learned_knowledge_filtered_trend_source_consistency()`
# (Prompt 540, above) already reduces every Prompt 536-539 check into a
# per-eligible-position breakdown ("sources") plus the usual "valid" /
# "well_formed" / "errors" envelope. This prompt adds no further
# detection on top of that - it is a second, small read-only
# summarization of the SAME Prompt 540 result, phrased around one
# question: does the set of source comparisons a filtered trend relies
# on give it COMPLETE, non-overlapping coverage of what it needs?
#
# `validate_learned_knowledge_filtered_trend_source_coverage()` calls
# Prompt 540 first, unchanged, then collapses its result into a single
# `"state"` - exactly one of the eight this prompt asks for - by
# reading for the first matching problem class, in this fixed priority
# order (most specific/actionable first):
#
#   1. `"invalid_input"`     - `trend_summary` is not well-formed on its
#                             own, or `comparisons` is not a list, a
#                             tuple, or `None` (Prompt 540/536's own
#                             `"invalid_source:comparisons"`). Nothing
#                             about coverage can be judged from here.
#   2. `"missing_source"`    - some eligible position's source is simply
#                             absent (Prompt 540's `"missing"` category
#                             on at least one position).
#   3. `"invalid_source"`    - some eligible position's source is
#                             present but malformed or independently
#                             invalid (Prompt 540's `"invalid_source"`
#                             category).
#   4. `"duplicate_source"`  - the same underlying source is relied on
#                             at more than one position (Prompt 540's
#                             `"duplicated"` category) - source
#                             comparison ids are not unique.
#   5. `"unexpected_source"` - a position's source does not continue the
#                             chain the trend actually needs, i.e. an
#                             unrelated comparison was included in its
#                             place (Prompt 540's `"ordering_mismatch"`
#                             category, renamed here to what it means
#                             from a coverage point of view: a source
#                             that does not belong).
#   6. `"ordering_mismatch"` - the sources agree on which snapshots they
#                             cover but contradict each other, or the
#                             declared chronology, about their order or
#                             identity (Prompt 540's `"mismatched"`
#                             category, or an inherited `"inconsistent_
#                             trend_chronology"` reversed-ordering
#                             error).
#   7. `"incomplete"`        - every represented source is individually
#                             fine, but the represented count does not
#                             match the coverage the trend expects (an
#                             inherited `"inconsistent_comparison_
#                             count"` error with no more specific
#                             problem above it).
#   8. `"complete"`          - none of the above: every required source
#                             is represented exactly once, in order, and
#                             independently valid.
#
# Only the FIRST matching class in that order is reported as `"state"`,
# so a single result names the most actionable problem rather than
# every symptom at once; the full, unfiltered Prompt 540 error list
# remains available in `"errors"` for anything more detailed. `"valid"`
# is `True` if and only if `"state"` is `"complete"` - identical to the
# Prompt 540 result's own `"valid"`, restated as the coverage state.
#
# `"coverage"` is exactly the Prompt 540 result's own `"sources"` -
# the same `{index: category}` breakdown, unchanged and unrenamed at
# the per-position level - so nothing about individual positions is
# lost even though `"state"` reports only the single most pressing
# class overall. An empty trend or one with zero eligible comparisons
# has `"coverage": {}` and reads `"state": "complete"`, exactly as
# Prompt 536/538/539/540 already treat these cases: there being nothing
# required is not itself a coverage problem.
#
# Reuses the existing filtered trend, filtered comparison, and
# validation structures throughout; creates no second trend or
# comparison system, no metric, prediction, score, rank, or
# recommendation. Never repairs, regenerates, reorders, or otherwise
# changes `trend_summary` or any comparison in `comparisons`, and never
# silently drops or replaces an invalid entry - every problem still
# surfaces in `"errors"` and, for what it names, in `"state"`. Not
# called from the gate/decision/response path. Deterministic: the same
# inputs always give an equal result.


_FILTERED_TREND_SOURCE_COVERAGE_STATES = (
    "complete", "incomplete", "missing_source", "duplicate_source",
    "unexpected_source", "invalid_source", "ordering_mismatch", "invalid_input",
)


def _filtered_trend_source_coverage_state(base):
    """The single Prompt 541 coverage state for a Prompt 540 result -
    exactly one of `_FILTERED_TREND_SOURCE_COVERAGE_STATES` - chosen by
    the fixed priority order the module note above documents. Reads
    only `base`'s own `"well_formed"`, `"errors"`, and `"sources"`;
    performs no detection of its own."""
    if not base["well_formed"] or "invalid_source:comparisons" in base["errors"]:
        return "invalid_input"

    categories = set(base["sources"].values())
    if "missing" in categories:
        return "missing_source"
    if "invalid_source" in categories:
        return "invalid_source"
    if "duplicated" in categories:
        return "duplicate_source"
    if "ordering_mismatch" in categories:
        return "unexpected_source"
    if "mismatched" in categories:
        return "ordering_mismatch"
    if any(e.startswith("inconsistent_trend_chronology:") for e in base["errors"]):
        return "ordering_mismatch"
    if any(e.startswith("inconsistent_comparison_count:") for e in base["errors"]):
        return "incomplete"
    if base["errors"]:
        # No known problem class matched but the result is still not
        # valid: treated as incomplete coverage rather than silently
        # folded into "complete".
        return "incomplete"
    return "complete"


def validate_learned_knowledge_filtered_trend_source_coverage(comparisons, trend_summary):
    """Deterministic, read-only check of whether the source comparisons
    `trend_summary` - a dict in the shape `summarize_learned_knowledge_
    filtered_summary_snapshot_comparison_trend()` (Prompt 520) returns -
    relies on (its eligible positions) give it complete, non-
    overlapping coverage of what it needs, on top of the existing
    Prompt 536/537/538/539/540 checks.

    Returns `{"valid", "well_formed", "errors", "warnings"}` exactly as
    `validate_learned_knowledge_filtered_trend_source_consistency()`
    (Prompt 540) reports them - this prompt adds no new detection -
    plus two additional, read-only fields: `"state"`, exactly one of
    `"complete"`, `"incomplete"`, `"missing_source"`, `"duplicate_
    source"`, `"unexpected_source"`, `"invalid_source"`, `"ordering_
    mismatch"`, or `"invalid_input"` (see the module note above for how
    it is chosen), and `"coverage"`, the Prompt 540 result's own
    `"sources"` mapping, unchanged.

    `comparisons` given as anything other than a list, a tuple, or
    `None`, or a `trend_summary` that is not well-formed, reads
    `"state": "invalid_input"` with `"coverage": {}` - no per-position
    coverage can be judged. An empty trend, a trend with zero eligible
    comparisons, or one with a single eligible comparison is handled
    like any other input.

    Never repairs, regenerates, or otherwise changes `trend_summary` or
    `comparisons`, and never silently removes or replaces an invalid
    entry; assigns no score, rank, or prediction. Deterministic: the
    same inputs always give an equal result.
    """
    base = validate_learned_knowledge_filtered_trend_source_consistency(comparisons, trend_summary)
    state = _filtered_trend_source_coverage_state(base)

    return {
        "valid": state == "complete",
        "well_formed": base["well_formed"],
        "state": state,
        "errors": list(base["errors"]),
        "warnings": [],
        "coverage": dict(base["sources"]),
    }


# ----------------------------------------------------------------------
# Prompt 542 - validate a Prompt 541 filtered trend source coverage
# result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check over the dict
# `validate_learned_knowledge_filtered_trend_source_coverage()`
# (Prompt 541, above) returns. This is a validator OF a validation
# result, not a second coverage system: it never calls Prompt 541, 540,
# or anything upstream of them, never re-derives coverage from raw
# comparisons or a trend summary, and never repairs, normalizes, or
# otherwise changes the `result` dict it is given - every problem
# found is reported, not fixed. It follows the same
# `{"valid", "errors", "warnings"}` envelope convention as
# `validate_learned_knowledge_statistics_analysis()` (Prompt 506).
#
# Everything this validator checks is already fully determined by
# `result`'s own fields - it needs nothing else:
#
#   - every field in `_FILTERED_TREND_SOURCE_COVERAGE_RESULT_REQUIRED_
#     FIELDS` is present (`"missing_field:<name>"` otherwise)
#   - `"valid"` and `"well_formed"` are each a plain `bool`
#     (`"invalid_type:valid"` / `"invalid_type:well_formed"`)
#   - `"state"` is one of the existing Prompt 541
#     `_FILTERED_TREND_SOURCE_COVERAGE_STATES` (`"invalid_state"`
#     otherwise)
#   - `"errors"` and `"warnings"` are each a list of `str`
#     (`"invalid_type:errors"` / `"invalid_type:warnings"`)
#   - `"coverage"` is a `dict` (`"invalid_type:coverage"` otherwise)
#     whose keys are each a non-negative plain `int`
#     (`"invalid_coverage_key:<repr>"`) and whose values are each one
#     of the existing Prompt 540
#     `_FILTERED_TREND_SOURCE_CONSISTENCY_CATEGORIES` shape - `"valid"`,
#     `"missing"`, `"invalid_source"`, `"duplicated"`,
#     `"ordering_mismatch"`, or `"mismatched"`
#     (`"invalid_coverage_category:<key>"` otherwise)
#   - once `"state"`, `"errors"`, `"well_formed"`, and `"coverage"` are
#     each individually well-formed enough to compare, `"state"` is
#     re-derived from `"coverage"`'s own categories and `"errors"`,
#     by the SAME fixed priority order
#     `_filtered_trend_source_coverage_state()` (Prompt 541) already
#     uses, and must match exactly
#     (`"state_inconsistent_with_coverage:<state>"` otherwise) - this
#     is what catches every contradictory combination the module note
#     for Prompt 541 defines: a `"complete"` state reported while some
#     position is `"missing"`, an `"invalid_source"` state reported
#     with no `"invalid_source"` category anywhere, a `"duplicate_
#     source"`, `"unexpected_source"`, `"ordering_mismatch"`, or
#     `"missing_source"` state unsupported by the matching category,
#     and an `"invalid_input"` state reported when `"well_formed"` is
#     `True` and no `"invalid_source:comparisons"` error is present
#     (i.e. the coverage result was not itself structurally invalid)
#   - once `"state"` and `"valid"` are each individually well-formed
#     enough to compare, `"valid"` is `True` exactly when `"state"` is
#     `"complete"`, exactly as Prompt 541 itself guarantees
#     (`"valid_inconsistent_with_state"` otherwise)
#
# A field that already failed its own type/membership check is left
# out of these cross-field checks - there is nothing meaningful to
# compare against, so a single bad field never cascades into extra,
# misleading consistency errors. `"coverage"` is always a required
# field here (Prompt 541 always includes it, even as `{}`), so there
# are no optional fields in this shape to skip; a `result` missing one
# is reported via `"missing_field:<name>"` like any other field,
# without raising.
#
# `result` given as anything other than a `dict` (including `None`)
# safely produces a single `"result_not_a_dict"` error rather than
# raising. Never mutates `result`, never repairs or reinterprets a
# problem it finds, assigns no score, rank, or prediction, and adds no
# new coverage/consistency/reference/integrity detection of its own -
# purely a structural check of what Prompt 541 already reported. Not
# called from the gate/decision/response path. Deterministic: the same
# `result` dict always produces an equal validation result, in the
# same order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_RESULT_REQUIRED_FIELDS = (
    "valid", "well_formed", "state", "errors", "warnings", "coverage",
)

# Identical to `_filtered_trend_source_consistency_category()`'s own
# possible outputs (Prompt 540) - reused here as a closed membership
# set, not redefined or reinterpreted.
_FILTERED_TREND_SOURCE_CONSISTENCY_CATEGORIES = (
    "valid", "missing", "invalid_source", "duplicated",
    "ordering_mismatch", "mismatched",
)


def _filtered_trend_source_coverage_expected_state(categories, errors, well_formed):
    """The Prompt 541 `\"state\"` that `categories` (the set of distinct
    `\"coverage\"` values present in a result) and `errors` and
    `well_formed` would justify, derived by the exact same fixed
    priority order `_filtered_trend_source_coverage_state()` (Prompt
    541) uses on a Prompt 540 result's own `\"sources\"`/`\"well_formed\"`/
    `\"errors\"`. Reads only its three arguments; performs no detection
    of its own and never looks at the original comparisons or trend
    summary."""
    if not well_formed or "invalid_source:comparisons" in errors:
        return "invalid_input"
    if "missing" in categories:
        return "missing_source"
    if "invalid_source" in categories:
        return "invalid_source"
    if "duplicated" in categories:
        return "duplicate_source"
    if "ordering_mismatch" in categories:
        return "unexpected_source"
    if "mismatched" in categories:
        return "ordering_mismatch"
    if any(isinstance(e, str) and e.startswith("inconsistent_trend_chronology:") for e in errors):
        return "ordering_mismatch"
    if any(isinstance(e, str) and e.startswith("inconsistent_comparison_count:") for e in errors):
        return "incomplete"
    if errors:
        return "incomplete"
    return "complete"


def validate_learned_knowledge_filtered_trend_source_coverage_result(result):
    """Deterministic, read-only structural validation of `result` - the
    dict shape `validate_learned_knowledge_filtered_trend_source_
    coverage()` (Prompt 541) returns. Returns a new, independent plain
    dict:

        {
            "valid": <bool>,
            "errors": [<str>, ...],
            "warnings": [<str>, ...],
        }

    `valid` is `True` exactly when `errors` is empty; `warnings` is
    always a list (currently always empty - this validator raises no
    warnings of its own, only errors) so callers have a stable shape
    to read regardless of outcome.

    See the module note above for exactly what is checked and every
    error code this can report. Never repairs, regenerates, or
    otherwise changes `result` - every problem found is reported, not
    fixed. Never mutates `result`, whatever it turns out to be (a
    non-dict `result`, including `None`, safely produces a single
    `"result_not_a_dict"` error rather than raising). Never re-runs or
    re-derives coverage, consistency, reference, or integrity checks
    from any underlying comparisons or trend summary - Prompt 541's
    result is the only thing read. Not called from the gate/decision/
    response path, and does not itself decide whether learned
    knowledge is accepted or rejected - purely descriptive.
    Deterministic: the same `result` dict always produces an equal
    validation result, in the same order, on every call.
    """
    if not isinstance(result, dict):
        return {"valid": False, "errors": ["result_not_a_dict"], "warnings": []}

    errors = []
    warnings = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_RESULT_REQUIRED_FIELDS:
        if field not in result:
            errors.append("missing_field:%s" % field)

    valid_ok = False
    if "valid" in result:
        if not isinstance(result["valid"], bool):
            errors.append("invalid_type:valid")
        else:
            valid_ok = True

    well_formed_ok = False
    if "well_formed" in result:
        if not isinstance(result["well_formed"], bool):
            errors.append("invalid_type:well_formed")
        else:
            well_formed_ok = True

    state_ok = False
    if "state" in result:
        if result["state"] not in _FILTERED_TREND_SOURCE_COVERAGE_STATES:
            errors.append("invalid_state")
        else:
            state_ok = True

    errors_ok = False
    if "errors" in result:
        value = result["errors"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append("invalid_type:errors")
        else:
            errors_ok = True

    if "warnings" in result:
        value = result["warnings"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append("invalid_type:warnings")

    coverage_ok = False
    valid_categories = set()
    if "coverage" in result:
        value = result["coverage"]
        if not isinstance(value, dict):
            errors.append("invalid_type:coverage")
        else:
            coverage_ok = True
            for key, category in value.items():
                if not _is_plain_int(key) or key < 0:
                    errors.append("invalid_coverage_key:%r" % (key,))
                elif category not in _FILTERED_TREND_SOURCE_CONSISTENCY_CATEGORIES:
                    errors.append("invalid_coverage_category:%s" % key)
                else:
                    valid_categories.add(category)

    if state_ok and errors_ok and well_formed_ok and coverage_ok:
        expected_state = _filtered_trend_source_coverage_expected_state(
            valid_categories, result["errors"], result["well_formed"])
        if result["state"] != expected_state:
            errors.append("state_inconsistent_with_coverage:%s" % result["state"])

    if state_ok and valid_ok:
        expected_valid = result["state"] == "complete"
        if result["valid"] != expected_valid:
            errors.append("valid_inconsistent_with_state")

    return {"valid": not errors, "errors": errors, "warnings": warnings}


# ----------------------------------------------------------------------
# Prompt 543 - validate coverage result / coverage-result-validation
# consistency
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY consistency check between a pair of
# dicts: a Prompt 541 filtered trend source coverage result
# (`validate_learned_knowledge_filtered_trend_source_coverage()`) and a
# Prompt 542 validation result claimed to describe it
# (`validate_learned_knowledge_filtered_trend_source_coverage_result()`).
# It is a validator OF that pairing, not a third coverage or validation
# system: it never calls Prompt 541, 540, or anything upstream of them,
# and never re-derives coverage from raw comparisons or a trend
# summary. The only new work it does is recompute Prompt 542 itself,
# unchanged, on `coverage_result`, and compare that recomputation
# against the `validation_result` it was given - so every check below
# is fully determined by delegating to Prompt 542, never by
# reimplementing any of its detection.
#
# `validate_learned_knowledge_filtered_trend_source_coverage_result_
# consistency(coverage_result, validation_result)`:
#
#   - `coverage_result` or `validation_result` given as anything other
#     than a `dict` is malformed pairing input - nothing meaningful can
#     be compared - and reads `"status": "invalid_input"` with
#     `"coverage_result_not_a_dict"` and/or `"validation_result_not_a_
#     dict"` in `"errors"` (one entry per side that is not a dict).
#   - Otherwise, `expected` is computed by calling Prompt 542 on
#     `coverage_result` exactly as it stands - this alone already
#     re-derives whether `coverage_result` is structurally valid,
#     whether its "state" matches its own "coverage" data, and every
#     "missing_field"/"invalid_type"/"invalid_state"/"invalid_coverage_
#     key"/"invalid_coverage_category"/"state_inconsistent_with_
#     coverage"/"valid_inconsistent_with_state" problem Prompt 542
#     already defines. Nothing about `coverage_result`'s own structure
#     is re-checked independently here.
#   - `validation_result` is then checked against the same
#     `{"valid", "errors", "warnings"}` envelope Prompt 542 always
#     returns: a missing field is `"validation_result_missing_field:
#     <name>"`; `"valid"` not a plain `bool` is `"validation_result_
#     invalid_type:valid"`; `"errors"`/`"warnings"` not a list of `str`
#     is `"validation_result_invalid_type:errors"` / `"...:warnings"`.
#   - Once `"valid"` is well-typed on both sides, a mismatch against
#     `expected["valid"]` is `"valid_mismatch:expected=<bool>,actual=
#     <bool>"` - this is what catches a structurally valid coverage
#     result reported invalid, or a structurally invalid one reported
#     fully valid.
#   - Once `"errors"` is well-typed, every code `expected["errors"]`
#     requires but `validation_result["errors"]` lacks is `"missing_
#     error:<code>"` (a real problem silently dropped), and every code
#     present in `validation_result["errors"]` but not justified by
#     `expected["errors"]` is `"fabricated_error:<code>"` (validation
#     information invented rather than found). The same two checks
#     apply to `"warnings"` as `"missing_warning:<code>"` / `"fabricated_
#     warning:<code>"`, for symmetry, even though Prompt 542 currently
#     never raises a warning of its own.
#   - A field that already failed its own type check is left out of
#     these value comparisons, exactly as Prompt 542 does for its own
#     cross-field checks - one bad field never cascades into misleading
#     extra errors.
#
# `"status"` is `"consistent"` when no error above was found, else
# `"inconsistent"` (or `"invalid_input"` for the non-dict case above,
# which takes precedence over both). `"warnings"` is always `[]` -
# this layer raises no warnings of its own, only errors - kept in the
# returned shape so callers have a stable envelope regardless of
# outcome.
#
# Reuses the existing Prompt 541/542 structures throughout; creates no
# second coverage or validation system, no metric, prediction, score,
# rank, or recommendation. Never mutates `coverage_result` or
# `validation_result`, never repairs or reinterprets a problem it
# finds - every mismatch is reported, not fixed. Not called from the
# gate/decision/response path. Deterministic: the same pair of dicts
# always produces an equal consistency result, in the same order, on
# every call.

_FILTERED_TREND_SOURCE_COVERAGE_VALIDATION_REQUIRED_FIELDS = ("valid", "errors", "warnings")


def validate_learned_knowledge_filtered_trend_source_coverage_result_consistency(
        coverage_result, validation_result):
    """Deterministic, read-only check of whether `validation_result` -
    claimed to be the dict `validate_learned_knowledge_filtered_trend_
    source_coverage_result()` (Prompt 542) returns for `coverage_result`
    - actually, accurately represents it.

    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `coverage_result` or `validation_result` given as anything other
    than a `dict` (including `None`) safely reads `"status":
    "invalid_input"` rather than raising, with `"coverage_result_not_a_
    dict"` and/or `"validation_result_not_a_dict"` in `"errors"`.

    Otherwise, this recomputes Prompt 542 on `coverage_result` itself
    (unchanged) and compares the result field-by-field against
    `validation_result`: a mismatched `"valid"`, a missing or fabricated
    entry in `"errors"`/`"warnings"`, or a malformed envelope field on
    `validation_result` each yields `"status": "inconsistent"` with the
    specific problem(s) in `"errors"`. See the module note above for
    every error code this can report.

    Never re-runs or re-derives coverage from any underlying
    comparisons or trend summary - Prompt 542's own recomputation is
    the only detection used. Never repairs, regenerates, or otherwise
    changes `coverage_result` or `validation_result`, and never
    mutates either. Not called from the gate/decision/response path.
    Deterministic: the same pair of dicts always produces an equal
    consistency result, in the same order, on every call.
    """
    if not isinstance(coverage_result, dict) or not isinstance(validation_result, dict):
        errors = []
        if not isinstance(coverage_result, dict):
            errors.append("coverage_result_not_a_dict")
        if not isinstance(validation_result, dict):
            errors.append("validation_result_not_a_dict")
        return {"status": "invalid_input", "errors": errors, "warnings": []}

    expected = validate_learned_knowledge_filtered_trend_source_coverage_result(coverage_result)

    errors = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_VALIDATION_REQUIRED_FIELDS:
        if field not in validation_result:
            errors.append("validation_result_missing_field:%s" % field)

    valid_ok = False
    if "valid" in validation_result:
        if not isinstance(validation_result["valid"], bool):
            errors.append("validation_result_invalid_type:valid")
        else:
            valid_ok = True

    errors_ok = False
    if "errors" in validation_result:
        value = validation_result["errors"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append("validation_result_invalid_type:errors")
        else:
            errors_ok = True

    warnings_ok = False
    if "warnings" in validation_result:
        value = validation_result["warnings"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append("validation_result_invalid_type:warnings")
        else:
            warnings_ok = True

    if valid_ok and validation_result["valid"] != expected["valid"]:
        errors.append("valid_mismatch:expected=%r,actual=%r" % (
            expected["valid"], validation_result["valid"]))

    if errors_ok:
        given_errors = validation_result["errors"]
        for code in expected["errors"]:
            if code not in given_errors:
                errors.append("missing_error:%s" % code)
        for code in given_errors:
            if code not in expected["errors"]:
                errors.append("fabricated_error:%s" % code)

    if warnings_ok:
        given_warnings = validation_result["warnings"]
        for code in expected["warnings"]:
            if code not in given_warnings:
                errors.append("missing_warning:%s" % code)
        for code in given_warnings:
            if code not in expected["warnings"]:
                errors.append("fabricated_warning:%s" % code)

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 544 - validate filtered trend source coverage CHAIN integrity
# ----------------------------------------------------------------------
# Prompts 541/542/543 each validate ONE link of a four-stage chain:
#
#   source comparisons -> coverage -> coverage validation
#                       -> coverage consistency validation
#
# i.e. `comparisons`/`trend_summary` -> `validate_learned_knowledge_
# filtered_trend_source_coverage()` (541) -> `validate_learned_
# knowledge_filtered_trend_source_coverage_result()` (542) ->
# `validate_learned_knowledge_filtered_trend_source_coverage_result_
# consistency()` (543). Nothing so far checks that a caller's claimed
# results for every link actually line up with one another end to end.
# `validate_learned_knowledge_filtered_trend_source_coverage_chain()`
# adds that check - and only that check: it calls 541, 542, and 543
# again, unchanged, on the SAME inputs the caller already used to reach
# each claimed stage, and compares each recomputation against what the
# caller claims for that stage, field by field. It adds no detection of
# its own and re-derives nothing that 541/542/543 do not already
# compute.
#
# `validate_learned_knowledge_filtered_trend_source_coverage_chain(
#      comparisons, trend_summary, coverage_result,
#      coverage_validation_result, consistency_result)`:
#
#   - `trend_summary`, `coverage_result`, `coverage_validation_result`,
#     or `consistency_result` given as anything other than a `dict`
#     (including `None`), or `comparisons` given as anything other than
#     a `list`, a `tuple`, or `None`, is malformed chain input - nothing
#     meaningful can be recomputed or compared - and reads `"status":
#     "invalid_input"` with one `"<name>_not_a_dict"` / `"comparisons_
#     invalid_type"` entry in `"errors"` per malformed argument. This is
#     the only case this function itself decides is malformed; a `dict`
#     with missing or wrong-shaped fields inside it is instead reported
#     as an ordinary `"inconsistent"` mismatch by the stage checks below
#     (541/542/543 already handle a malformed `dict` gracefully without
#     raising).
#   - Stage 1 (source comparisons -> coverage): recomputes Prompt 541 on
#     `comparisons`/`trend_summary`, unchanged, and compares it against
#     `coverage_result` field by field. This is what verifies the
#     source comparisons a coverage result claims to summarize really
#     are the expected sources, that its `"state"` matches the source
#     coverage information, and that source ids, earlier/later snapshot
#     ids, and comparison ordering embedded in `"coverage"`'s per-
#     position categories are the ones `comparisons`/`trend_summary`
#     actually produce - a single dict-equality check on `"coverage"`
#     already catches any position silently lost or invented.
#   - Stage 2 (coverage -> coverage validation): recomputes Prompt 542
#     on `coverage_result` AS GIVEN (not stage 1's recomputation - a
#     stage 1 mismatch is already reported on its own and never masks
#     or double-counts a stage 2 problem), and compares it against
#     `coverage_validation_result` field by field.
#   - Stage 3 (coverage + coverage validation -> coverage consistency
#     validation): recomputes Prompt 543 on `coverage_result` and
#     `coverage_validation_result` AS GIVEN, and compares it against
#     `consistency_result` field by field. Prompt 543 already compares
#     both of its inputs against each other, so this is what verifies
#     `consistency_result` matches BOTH previous validation stages.
#   - Each field comparison reports, per field: `"stage:<stage>:
#     missing_field:<name>"` for a field the recomputation has but the
#     claimed stage result lacks (information silently dropped),
#     `"stage:<stage>:mismatched_field:<name>"` for a field present on
#     both sides with different values (including a `dict`/`list`
#     field, so any lost, invented, or reordered entry inside `"errors"`
#     or `"coverage"` surfaces as a single mismatch on that field), and
#     `"stage:<stage>:unexpected_field:<name>"` for a field the claimed
#     stage result has that the recomputation does not (information
#     invented rather than found). `<stage>` is one of `"coverage"`,
#     `"coverage_validation"`, or `"consistency"`, so every error names
#     exactly which link of the chain it was found on.
#
# `"status"` is `"consistent"` when no stage reports a problem, else
# `"inconsistent"` (or `"invalid_input"` for the malformed-argument case
# above, which takes precedence over all three stage checks).
# `"warnings"` is always `[]` - this layer raises no warnings of its
# own, only errors - kept in the returned shape so callers have a
# stable envelope regardless of outcome. Invalid information at any
# stage is never silently accepted: an `"invalid_input"`/`"invalid_
# source"`/etc. state that a claimed stage result contradicts is
# reported exactly like any other field mismatch, not treated as a
# special case.
#
# Reuses Prompts 541, 542, and 543 exactly as they stand throughout;
# creates no second coverage, validation, or trend architecture, no
# metric, prediction, score, rank, or recommendation. Never repairs,
# regenerates, or otherwise changes `comparisons`, `trend_summary`,
# `coverage_result`, `coverage_validation_result`, or
# `consistency_result`, and never mutates any of them. Not called from
# the gate/decision/response path. Deterministic: the same five
# arguments always produce an equal chain result, in the same order, on
# every call.

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGES = ("coverage", "coverage_validation", "consistency")


def _filtered_trend_source_coverage_chain_stage_diff(expected, actual, stage):
    """The list of `"stage:<stage>:..."` field-mismatch error codes
    between a freshly recomputed stage envelope `expected` and the
    caller's claimed `actual` envelope for that same stage - both
    already known to be `dict`s. Performs no detection of its own
    beyond a plain field-by-field comparison; `expected` is always
    produced by calling the existing Prompt 541/542/543 validator for
    the stage, unchanged."""
    errors = []
    for field, value in expected.items():
        if field not in actual:
            errors.append("stage:%s:missing_field:%s" % (stage, field))
        elif actual[field] != value:
            errors.append("stage:%s:mismatched_field:%s" % (stage, field))
    for field in actual:
        if field not in expected:
            errors.append("stage:%s:unexpected_field:%s" % (stage, field))
    return errors


def validate_learned_knowledge_filtered_trend_source_coverage_chain(
        comparisons, trend_summary, coverage_result,
        coverage_validation_result, consistency_result):
    """Deterministic, read-only check that a caller's claimed results
    for every link of the four-stage filtered trend source coverage
    validation chain - source comparisons -> coverage (Prompt 541) ->
    coverage validation (Prompt 542) -> coverage consistency validation
    (Prompt 543) - actually correspond to one another, end to end.

    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `trend_summary`, `coverage_result`, `coverage_validation_result`, or
    `consistency_result` given as anything other than a `dict`
    (including `None`), or `comparisons` given as anything other than a
    `list`, a `tuple`, or `None`, safely reads `"status": "invalid_
    input"` rather than raising, with one `"<name>_not_a_dict"` /
    `"comparisons_invalid_type"` entry per malformed argument.

    Otherwise this recomputes Prompt 541 on `comparisons`/
    `trend_summary`, Prompt 542 on `coverage_result` as given, and
    Prompt 543 on `coverage_result`/`coverage_validation_result` as
    given - each unchanged - and compares each recomputation against
    the caller's matching claimed result field by field. See the module
    note above for exactly what this catches and every error code this
    can report, each one naming the specific chain link (`"coverage"`,
    `"coverage_validation"`, or `"consistency"`) it was found on.

    Never re-runs or re-derives anything beyond calling Prompt 541,
    542, and 543 as they already stand - no second coverage, validation,
    or trend system. Never repairs, regenerates, or otherwise changes
    any of its five arguments, and never mutates any of them. Not
    called from the gate/decision/response path. Deterministic: the
    same five arguments always produce an equal chain result, in the
    same order, on every call.
    """
    errors = []
    if comparisons is not None and not isinstance(comparisons, (list, tuple)):
        errors.append("comparisons_invalid_type")
    if not isinstance(trend_summary, dict):
        errors.append("trend_summary_not_a_dict")
    if not isinstance(coverage_result, dict):
        errors.append("coverage_result_not_a_dict")
    if not isinstance(coverage_validation_result, dict):
        errors.append("coverage_validation_result_not_a_dict")
    if not isinstance(consistency_result, dict):
        errors.append("consistency_result_not_a_dict")
    if errors:
        return {"status": "invalid_input", "errors": errors, "warnings": []}

    errors = []

    expected_coverage = validate_learned_knowledge_filtered_trend_source_coverage(
        comparisons, trend_summary)
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_coverage, coverage_result, "coverage"))

    expected_coverage_validation = validate_learned_knowledge_filtered_trend_source_coverage_result(
        coverage_result)
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_coverage_validation, coverage_validation_result, "coverage_validation"))

    expected_consistency = validate_learned_knowledge_filtered_trend_source_coverage_result_consistency(
        coverage_result, coverage_validation_result)
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_consistency, consistency_result, "consistency"))

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 545 - validate coverage chain stage ordering
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check that the STAGES of
# the filtered trend source coverage validation chain - not their
# values - appear in the correct logical order:
#
#   source comparisons -> coverage -> coverage validation
#                       -> coverage consistency validation
#                       -> chain integrity validation
#
# This is an ordering check, not a value check: Prompts 541-544 already
# verify that each stage's DATA is correct (via recomputation and
# field-by-field comparison); this prompt never recomputes or compares
# any of that data. It instead validates a caller-supplied description
# of the SEQUENCE the chain's stages were produced in - a list of
# `{"stage": <name>, "source": <name-or-None>}` entries, one per stage
# actually present, in the order the caller presents them - plus an
# optional declared `stage_order` list a caller may attach as
# metadata describing what order it believes the chain to be in.
#
# `validate_learned_knowledge_filtered_trend_source_coverage_chain_
# stage_order(chain_stages, stage_order=None)`:
#
#   - `chain_stages` given as anything other than a `list` or a `tuple`,
#     or any entry in it that is not a `dict` with a non-empty `str`
#     `"stage"` (and, if present, a `"source"` that is `None` or a
#     non-empty `str`), or a given `stage_order` that is not a `list`/
#     `tuple` of non-empty `str` - malformed stage metadata - safely
#     reads `"state": "invalid_input"` rather than raising, with one
#     `"chain_stages_invalid_type"` / `"invalid_stage_entry:<index>"` /
#     `"stage_order_invalid_type"` / `"invalid_stage_order_entry:
#     <index>"` entry per problem found, and nothing further is
#     checked.
#   - Otherwise, each entry's `"stage"` is compared against the fixed
#     five-name canonical sequence above:
#       * a canonical name absent from `chain_stages` entirely is
#         `"missing_stage:<name>"` - required stages are never silently
#         skipped, whether the chain is completely empty (nothing
#         required is ever inferred as satisfied) or missing just one
#         stage in the middle;
#       * a name present that is not one of the five canonical stages
#         is `"unexpected_stage:<name>"`;
#       * a canonical name that appears more than once is
#         `"duplicate_stage:<name>"`.
#   - The relative order of first appearances of recognized (canonical)
#     stage names is required to strictly follow the canonical
#     sequence - any recognized stage appearing before a canonical
#     stage that must precede it (including a fully reversed chain) is
#     `"invalid_order:sequence"`.
#   - Each entry's own `"source"`, when given and itself a recognized
#     canonical stage name, must not be a stage that comes at or after
#     the entry's own stage in the canonical sequence - a stage that
#     names a later (or the same) stage as its source is
#     `"invalid_order:source_not_before_stage:<name>"`. This is what
#     catches a stage evaluated against the wrong (or a not-yet-
#     produced) previous stage.
#   - When `stage_order` is given, it must equal, in order, the list of
#     `"stage"` names taken from `chain_stages` exactly as given -
#     otherwise `"invalid_order:stage_order_metadata_mismatch"` is
#     added: declared stage-ordering metadata that disagrees with the
#     actual chain order is never silently accepted.
#
# `"state"` is exactly one of `"valid"`, `"invalid_order"`,
# `"missing_stage"`, `"unexpected_stage"`, `"duplicate_stage"`, or
# `"invalid_input"`, chosen by a fixed priority (invalid input first,
# then missing, then unexpected, then duplicate, then any ordering
# problem, else valid) so a single result names the most pressing
# problem while every problem found remains listed in `"errors"`.
# `"valid"` is `True` if and only if `"state"` is `"valid"`.
#
# Reuses the existing five-stage chain this module already builds
# (Prompts 541-544, plus the raw source comparisons) as its vocabulary
# of stage names; creates no second validation-chain architecture, no
# metric, prediction, score, rank, or recommendation. Never repairs,
# reorders, or otherwise changes `chain_stages` or `stage_order`, and
# never mutates either. Not called from the gate/decision/response
# path. Deterministic: the same two arguments always produce an equal
# result, in the same order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE = (
    "source_comparisons",
    "coverage",
    "coverage_validation",
    "coverage_consistency_validation",
    "chain_integrity_validation",
)

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_STATES = (
    "valid", "invalid_order", "missing_stage", "unexpected_stage",
    "duplicate_stage", "invalid_input",
)


def _filtered_trend_source_coverage_chain_stage_order_input_errors(chain_stages, stage_order):
    """The list of malformed-input error codes for `chain_stages` and
    `stage_order`, or `[]` if both are well-formed enough to validate
    further. Performs no ordering detection of its own - purely a
    shape check."""
    errors = []

    if not isinstance(chain_stages, (list, tuple)):
        errors.append("chain_stages_invalid_type")
    else:
        for index, entry in enumerate(chain_stages):
            if not isinstance(entry, dict):
                errors.append("invalid_stage_entry:%d" % index)
                continue
            stage_name = entry.get("stage")
            if not isinstance(stage_name, str) or not stage_name:
                errors.append("invalid_stage_entry:%d" % index)
                continue
            if "source" in entry:
                source = entry["source"]
                if source is not None and (not isinstance(source, str) or not source):
                    errors.append("invalid_stage_entry:%d" % index)

    if stage_order is not None:
        if not isinstance(stage_order, (list, tuple)):
            errors.append("stage_order_invalid_type")
        else:
            for index, name in enumerate(stage_order):
                if not isinstance(name, str) or not name:
                    errors.append("invalid_stage_order_entry:%d" % index)

    return errors


def validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order(
        chain_stages, stage_order=None):
    """Deterministic, read-only check that `chain_stages` - a list of
    `{"stage": <name>, "source": <name-or-None>}` entries describing,
    in order, the stages of the filtered trend source coverage
    validation chain a caller claims to have produced - actually
    follows the chain's required logical order:

        source comparisons -> coverage -> coverage validation
                            -> coverage consistency validation
                            -> chain integrity validation

    Returns a new, independent plain dict:

        {
            "valid": <bool>,
            "state": <one of `_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_
                       STAGE_ORDER_STATES`>,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `chain_stages` given as anything other than a `list`/`tuple`, any
    entry that is not a well-formed `{"stage": <str>, "source":
    <str-or-None>}` dict, or a given `stage_order` that is not a
    `list`/`tuple` of non-empty `str` safely reads `"state": "invalid_
    input"` rather than raising.

    Otherwise this checks, purely from the `"stage"`/`"source"` names
    given - never from any comparison, trend, coverage, or validation
    VALUE - that every one of the five canonical stages is present
    exactly once, that no unrecognized stage name appears, that
    recognized stages appear in the correct relative order, that no
    stage's `"source"` names a stage at or after its own position, and
    that `stage_order`, when given, matches the actual order of
    `chain_stages` exactly. See the module note above for every error
    code this can report.

    Never re-runs or re-derives anything from Prompt 541, 542, 543, or
    544 - this is an ordering check over caller-supplied stage
    descriptions, not a value check. Never repairs, reorders, or
    otherwise changes `chain_stages` or `stage_order`, and never
    mutates either. Not called from the gate/decision/response path.
    Deterministic: the same two arguments always produce an equal
    result, in the same order, on every call.
    """
    input_errors = _filtered_trend_source_coverage_chain_stage_order_input_errors(
        chain_stages, stage_order)
    if input_errors:
        return {"valid": False, "state": "invalid_input", "errors": input_errors, "warnings": []}

    canonical = _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_SEQUENCE
    canonical_set = set(canonical)
    names_in_order = [entry["stage"] for entry in chain_stages]

    errors = []

    seen = set()
    duplicates = set()
    for name in names_in_order:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    for name in sorted(duplicates):
        errors.append("duplicate_stage:%s" % name)

    unexpected = sorted(set(name for name in names_in_order if name not in canonical_set))
    for name in unexpected:
        errors.append("unexpected_stage:%s" % name)

    present_canonical = set(name for name in names_in_order if name in canonical_set)
    for name in canonical:
        if name not in present_canonical:
            errors.append("missing_stage:%s" % name)

    first_seen_index = {}
    for position, name in enumerate(names_in_order):
        if name in canonical_set and name not in first_seen_index:
            first_seen_index[name] = position
    appearance_order = sorted(first_seen_index.items(), key=lambda pair: pair[1])
    canonical_indices = [canonical.index(name) for name, _ in appearance_order]
    sequence_ok = all(
        canonical_indices[i] < canonical_indices[i + 1]
        for i in range(len(canonical_indices) - 1)
    )
    if not sequence_ok:
        errors.append("invalid_order:sequence")

    for entry in chain_stages:
        name = entry["stage"]
        source = entry.get("source")
        if name in canonical_set and isinstance(source, str) and source in canonical_set:
            if canonical.index(source) >= canonical.index(name):
                errors.append("invalid_order:source_not_before_stage:%s" % name)

    if stage_order is not None and list(stage_order) != names_in_order:
        errors.append("invalid_order:stage_order_metadata_mismatch")

    if any(error.startswith("missing_stage:") for error in errors):
        state = "missing_stage"
    elif any(error.startswith("unexpected_stage:") for error in errors):
        state = "unexpected_stage"
    elif any(error.startswith("duplicate_stage:") for error in errors):
        state = "duplicate_stage"
    elif any(error.startswith("invalid_order") for error in errors):
        state = "invalid_order"
    else:
        state = "valid"

    return {"valid": state == "valid", "state": state, "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 546 - validate a Prompt 545 stage-order result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check over the dict
# `validate_learned_knowledge_filtered_trend_source_coverage_chain_
# stage_order()` (Prompt 545) returns. This is a validator OF that
# result, not a second stage-order system: it never calls Prompt 545
# or anything upstream of it, never re-derives ordering from any
# `chain_stages`/`stage_order` input, and never repairs, normalizes,
# or otherwise changes the `result` dict it is given - every problem
# found is reported, not fixed. It follows the same
# `{"status", "errors", "warnings"}` envelope convention as
# `validate_learned_knowledge_filtered_trend_source_coverage_result_
# consistency()` (Prompt 543) and `..._chain()` (Prompt 544).
#
# Everything this validator checks is already fully determined by
# `result`'s own fields:
#
#   - every field in `_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_
#     ORDER_RESULT_REQUIRED_FIELDS` is present (`"missing_field:<n>"`
#     otherwise)
#   - `"valid"` is a plain `bool` (`"invalid_type:valid"` otherwise)
#   - `"state"` is one of the existing Prompt 545
#     `_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_STATES`
#     (`"invalid_state"` otherwise)
#   - `"errors"` and `"warnings"` are each a `list` of `str`
#     (`"invalid_type:errors"` / `"invalid_type:warnings"` otherwise)
#   - once `"errors"` is well-typed, every entry in it is checked
#     against Prompt 545's own fixed error-code vocabulary: a code
#     using one of Prompt 545's stage-bearing prefixes
#     (`"missing_stage:"`, `"unexpected_stage:"`, `"duplicate_stage:"`,
#     `"invalid_order:source_not_before_stage:"`, `"invalid_stage_
#     entry:"`, `"invalid_stage_order_entry:"`) but with an empty
#     stage-name/index suffix is `"malformed_stage_information:
#     <code>"`; a code outside Prompt 545's vocabulary entirely (never
#     produced by Prompt 545, so it can only have been invented) is
#     `"unrecognized_error_code:<code>"`
#   - once `"warnings"` is well-typed, every entry in it is
#     `"fabricated_warning:<code>"` - Prompt 545 never raises a
#     warning of its own, so any warning present was invented
#   - once `"state"` and `"errors"` are each individually well-formed
#     enough to compare, `"state"` is re-derived from the categories
#     of codes present in `"errors"`, by the SAME fixed priority order
#     Prompt 545's own implementation uses (an input-error code first,
#     then `"missing_stage:"`, then `"unexpected_stage:"`, then
#     `"duplicate_stage:"`, then any `"invalid_order"` code, else
#     `"valid"`), and must match exactly
#     (`"state_inconsistent_with_errors:<state>"` otherwise) - this is
#     what catches `"missing_stage"`/`"duplicate_stage"`/`"unexpected_
#     stage"`/`"invalid_order"` reported with no matching evidence in
#     `"errors"`, evidence present but a different (or `"valid"`)
#     state reported instead, and an `"invalid_input"` state reported
#     with no input-error code present (or vice versa)
#   - once `"state"` and `"valid"` are each individually well-formed
#     enough to compare, `"valid"` is `True` exactly when `"state"` is
#     `"valid"`, exactly as Prompt 545 itself guarantees
#     (`"valid_inconsistent_with_state"` otherwise) - `"valid"` can
#     never be `True` while `"state"` names an invalid condition
#
# A field that already failed its own type/membership check is left
# out of these cross-field checks - there is nothing meaningful to
# compare against, so a single bad field never cascades into extra,
# misleading consistency errors.
#
# `"status"` is `"invalid_input"` only when `result` itself is not a
# `dict` (malformed validation input, `"result_not_a_dict"`) -
# reserved for that case alone, never for a content-level problem
# inside an otherwise well-typed dict. Any content-level problem found
# above yields `"status": "inconsistent"`; no problem found yields
# `"status": "consistent"`. `"warnings"` is always `[]` - this layer
# raises no warnings of its own, only errors.
#
# Reuses the existing Prompt 545 result shape and error-code
# vocabulary throughout; creates no second stage-order or validation
# system, no metric, prediction, score, rank, or recommendation. Never
# mutates `result`, never repairs or reinterprets a problem it finds,
# and never changes the stage-order calculation, the filtered trend
# system, or the coverage chain. Not called from the gate/decision/
# response path. Deterministic: the same `result` dict always produces
# an equal validation result, in the same order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_RESULT_REQUIRED_FIELDS = (
    "valid", "state", "errors", "warnings",
)

# Error codes `validate_learned_knowledge_filtered_trend_source_
# coverage_chain_stage_order()` (Prompt 545) can produce with no
# further suffix - matched by exact equality.
_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_EXACT_ERROR_CODES = (
    "chain_stages_invalid_type",
    "stage_order_invalid_type",
    "invalid_order:sequence",
    "invalid_order:stage_order_metadata_mismatch",
)

# Error codes Prompt 545 can produce with a required non-empty
# stage-name or index suffix appended after the prefix.
_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_PREFIXED_ERROR_CODES = (
    "missing_stage:",
    "unexpected_stage:",
    "duplicate_stage:",
    "invalid_order:source_not_before_stage:",
    "invalid_stage_entry:",
    "invalid_stage_order_entry:",
)

# The subset of the above prefixes that, when present anywhere in
# `"errors"`, mean the ORIGINAL `chain_stages`/`stage_order` input to
# Prompt 545 was itself malformed - matches Prompt 545's own
# `"invalid_input"` precedence.
_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_INPUT_ERROR_PREFIXES = (
    "chain_stages_invalid_type",
    "invalid_stage_entry:",
    "stage_order_invalid_type",
    "invalid_stage_order_entry:",
)


def _filtered_trend_source_coverage_chain_stage_order_error_code_problem(code):
    """`None` if `code` is a recognized Prompt 545 error code with
    valid structure, else the specific problem: `"unrecognized_error_
    code:<code>"` for a code outside Prompt 545's fixed vocabulary, or
    `"malformed_stage_information:<code>"` for a recognized prefix
    whose required stage-name/index suffix is empty. Performs no
    detection of its own beyond a shape check of `code`'s own text."""
    if code in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_EXACT_ERROR_CODES:
        return None
    for prefix in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_PREFIXED_ERROR_CODES:
        if code.startswith(prefix):
            if len(code) > len(prefix):
                return None
            return "malformed_stage_information:%s" % code
    return "unrecognized_error_code:%s" % code


def _filtered_trend_source_coverage_chain_stage_order_expected_state(errors):
    """The Prompt 545 `\"state\"` that the categories of codes present
    in `errors` would justify, derived by the exact same fixed
    priority order `validate_learned_knowledge_filtered_trend_source_
    coverage_chain_stage_order()` (Prompt 545) itself uses. Reads only
    `errors`; performs no detection of its own and never looks at any
    `chain_stages`/`stage_order` input."""
    if any(code.startswith(_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_INPUT_ERROR_PREFIXES)
           for code in errors):
        return "invalid_input"
    if any(code.startswith("missing_stage:") for code in errors):
        return "missing_stage"
    if any(code.startswith("unexpected_stage:") for code in errors):
        return "unexpected_stage"
    if any(code.startswith("duplicate_stage:") for code in errors):
        return "duplicate_stage"
    if any(code.startswith("invalid_order") for code in errors):
        return "invalid_order"
    return "valid"


def validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_result(result):
    """Deterministic, read-only structural validation of `result` -
    the dict shape `validate_learned_knowledge_filtered_trend_source_
    coverage_chain_stage_order()` (Prompt 545) returns. Returns a new,
    independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `result` given as anything other than a `dict` (including `None`)
    safely reads `"status": "invalid_input"` with `"result_not_a_
    dict"` in `"errors"`, rather than raising - the only case that
    reads `"invalid_input"` here.

    Otherwise this checks `result`'s own fields for missing/mis-typed
    entries, checks every code in `"errors"`/`"warnings"` against
    Prompt 545's fixed error-code vocabulary, and re-derives the
    expected `"state"` from the categories of codes actually present
    in `"errors"` - comparing it against the reported `"state"` and
    `"valid"`. See the module note above for every problem this can
    report; each yields `"status": "inconsistent"`. No problem found
    yields `"status": "consistent"`.

    Never re-runs or re-derives anything from Prompt 545's own
    `chain_stages`/`stage_order` input - only `result`'s own fields are
    read. Never repairs, normalizes, or otherwise changes `result`, and
    never mutates it. Not called from the gate/decision/response path.
    Deterministic: the same `result` dict always produces an equal
    validation result, in the same order, on every call.
    """
    if not isinstance(result, dict):
        return {"status": "invalid_input", "errors": ["result_not_a_dict"], "warnings": []}

    errors = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_RESULT_REQUIRED_FIELDS:
        if field not in result:
            errors.append("missing_field:%s" % field)

    valid_ok = "valid" in result and isinstance(result["valid"], bool)
    if "valid" in result and not valid_ok:
        errors.append("invalid_type:valid")

    state_ok = ("state" in result and isinstance(result["state"], str)
                and result["state"] in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_STATES)
    if "state" in result and not state_ok:
        errors.append("invalid_state")

    errors_ok = ("errors" in result and isinstance(result["errors"], list)
                 and all(isinstance(code, str) for code in result["errors"]))
    if "errors" in result and not errors_ok:
        errors.append("invalid_type:errors")

    warnings_ok = ("warnings" in result and isinstance(result["warnings"], list)
                   and all(isinstance(code, str) for code in result["warnings"]))
    if "warnings" in result and not warnings_ok:
        errors.append("invalid_type:warnings")

    if errors_ok:
        for code in result["errors"]:
            problem = _filtered_trend_source_coverage_chain_stage_order_error_code_problem(code)
            if problem is not None:
                errors.append(problem)

    if warnings_ok:
        for code in result["warnings"]:
            errors.append("fabricated_warning:%s" % code)

    if state_ok and errors_ok:
        expected_state = _filtered_trend_source_coverage_chain_stage_order_expected_state(
            result["errors"])
        if result["state"] != expected_state:
            errors.append("state_inconsistent_with_errors:%s" % result["state"])

    if state_ok and valid_ok:
        expected_valid = result["state"] == "valid"
        if result["valid"] != expected_valid:
            errors.append("valid_inconsistent_with_state")

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 547 - validate a Prompt 545 stage-order result against the
# source chain it claims to describe
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY consistency check tying together
# three things that, so far, have only ever been checked against each
# other in pairs:
#
#   - `chain_stages`/`stage_order` - the raw stage-sequence description
#     a caller supplies to Prompt 545
#   - the Prompt 545 stage-order result a caller claims for that
#     description
#   - the Prompt 546 result a caller claims for validating that
#     Prompt 545 result
#
# This is a two-link chain check, in exactly the same shape as
# `validate_learned_knowledge_filtered_trend_source_coverage_chain()`
# (Prompt 544): it adds no detection of its own. It recomputes Prompt
# 545 on `chain_stages`/`stage_order` and Prompt 546 on the caller's
# claimed Prompt 545 result - each unchanged - and compares each
# recomputation against what the caller claims for that link, field by
# field, using the same `_filtered_trend_source_coverage_chain_stage_
# diff()` helper Prompt 544 already uses.
#
# Because the comparison is field-by-field against a freshly recomputed
# Prompt 545/546 result, this single mechanism is what satisfies every
# item on the consistency checklist at once, with no extra machinery:
#
#   - a `"state"`/`"valid"`/`"errors"`/`"warnings"` that does not match
#     what Prompt 545 actually computes for `chain_stages`/`stage_
#     order` - including a required stage wrongly reported present or
#     missing, a duplicate or unexpected stage wrongly reported or
#     omitted, an `"invalid_order"` wrongly reported or omitted, or a
#     `"valid"`/`"valid"`-state claimed for a chain that is not - shows
#     up as a `"stage:order_result:mismatched_field:<field>"` /
#     `"stage:order_result:missing_field:<field>"` / `"stage:order_
#     result:unexpected_field:<field>"` entry;
#   - a Prompt 546 validation result that does not agree with what
#     Prompt 546 actually computes for the caller's claimed Prompt 545
#     result shows up the same way, prefixed `"stage:order_result_
#     validation:"`;
#   - a fabricated or silently omitted stage, error code, or source
#     reference always changes `"errors"` (or `"coverage"`-shaped
#     fields), so it is always caught by the same per-field comparison
#     - no separate fabrication/omission detector is needed.
#
# `chain_stages` given as anything other than a `list`/`tuple`, a given
# `stage_order` that is not `None` and not a `list`/`tuple`, or
# `order_result`/`order_result_validation` given as anything other than
# a `dict` (including `None`) safely reads `"status": "invalid_input"`
# rather than raising, with one `"chain_stages_invalid_type"` /
# `"stage_order_invalid_type"` / `"order_result_not_a_dict"` /
# `"order_result_validation_not_a_dict"` entry per malformed argument -
# matching exactly how Prompt 544 treats its own raw/claimed-result
# arguments. A `chain_stages`/`stage_order` pair that is well-typed but
# semantically invalid (e.g. missing a required stage) is not an
# `"invalid_input"` here - Prompt 545 already reports that as its own
# `"state"`, and this validator simply checks the caller's claim
# against it like any other field.
#
# Never re-runs or re-derives anything beyond calling Prompt 545 and
# 546 as they already stand - no second stage-order or validation
# system. Never repairs, reorders, or otherwise changes `chain_stages`,
# `stage_order`, `order_result`, or `order_result_validation`, and
# never mutates any of them. Not called from the gate/decision/response
# path. Deterministic: the same four arguments always produce an equal
# result, in the same order, on every call.

def validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency(
        chain_stages, stage_order, order_result, order_result_validation):
    """Deterministic, read-only check that a caller's claimed Prompt
    545 stage-order result `order_result` - and the caller's claimed
    Prompt 546 validation of it, `order_result_validation` - actually
    correspond to the `chain_stages`/`stage_order` description they
    claim to be about.

    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `chain_stages` given as anything other than a `list`/`tuple`, a
    given `stage_order` that is not `None` and not a `list`/`tuple`, or
    `order_result`/`order_result_validation` given as anything other
    than a `dict` (including `None`) safely reads `"status": "invalid_
    input"` rather than raising, with one `"chain_stages_invalid_
    type"` / `"stage_order_invalid_type"` / `"order_result_not_a_
    dict"` / `"order_result_validation_not_a_dict"` entry per malformed
    argument.

    Otherwise this recomputes Prompt 545 on `chain_stages`/`stage_
    order`, and Prompt 546 on `order_result` as given - each unchanged
    - and compares each recomputation against the caller's matching
    claimed result field by field. See the module note above for
    exactly what this catches; every mismatch names the specific link
    (`"order_result"` or `"order_result_validation"`) it was found on.

    Never re-runs or re-derives anything beyond calling Prompt 545 and
    546 as they already stand - no second stage-order or validation
    system. Never repairs, regenerates, or otherwise changes any of its
    four arguments, and never mutates any of them. Not called from the
    gate/decision/response path. Deterministic: the same four arguments
    always produce an equal result, in the same order, on every call.
    """
    errors = []
    if not isinstance(chain_stages, (list, tuple)):
        errors.append("chain_stages_invalid_type")
    if stage_order is not None and not isinstance(stage_order, (list, tuple)):
        errors.append("stage_order_invalid_type")
    if not isinstance(order_result, dict):
        errors.append("order_result_not_a_dict")
    if not isinstance(order_result_validation, dict):
        errors.append("order_result_validation_not_a_dict")
    if errors:
        return {"status": "invalid_input", "errors": errors, "warnings": []}

    errors = []

    expected_order_result = validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order(
        chain_stages, stage_order)
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_order_result, order_result, "order_result"))

    expected_order_result_validation = validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_result(
        order_result)
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_order_result_validation, order_result_validation, "order_result_validation"))

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 548 - validate a Prompt 547 consistency result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check over the dict
# `validate_learned_knowledge_filtered_trend_source_coverage_chain_
# stage_order_consistency()` (Prompt 547) returns. This is a validator
# OF that result, not a second consistency system: it never calls
# Prompt 547 or anything upstream of it (Prompt 545, 546, or the
# `chain_stages`/`stage_order`/`order_result`/`order_result_
# validation` inputs), and never repairs, normalizes, or otherwise
# changes the `result` dict it is given - every problem found is
# reported, not fixed. It follows the same `{"status", "errors",
# "warnings"}` envelope convention Prompt 547 itself uses, and the same
# validator-of-a-result shape `validate_learned_knowledge_filtered_
# trend_source_coverage_chain_stage_order_result()` (Prompt 546) uses.
#
# Everything this validator checks is already fully determined by
# `result`'s own fields:
#
#   - every field in `_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_
#     ORDER_CONSISTENCY_RESULT_REQUIRED_FIELDS` is present
#     (`"missing_field:<n>"` otherwise)
#   - `"status"` is one of the existing Prompt 547
#     `_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_
#     STATUSES` (`"invalid_status"` otherwise, whether the value is the
#     wrong type entirely - e.g. a plain `bool` - or simply an
#     unrecognized string)
#   - `"errors"` and `"warnings"` are each a `list` of `str`
#     (`"invalid_type:errors"` / `"invalid_type:warnings"` otherwise)
#   - once `"errors"` is well-typed, every entry in it is checked
#     against Prompt 547's own fixed error-code vocabulary: the four
#     exact input-error codes (`"chain_stages_invalid_type"`,
#     `"stage_order_invalid_type"`, `"order_result_not_a_dict"`,
#     `"order_result_validation_not_a_dict"`), and the per-link
#     structural-diff codes `"stage:order_result:<kind>:<field>"` /
#     `"stage:order_result_validation:<kind>:<field>"` (`<kind>` being
#     `"missing_field"`, `"mismatched_field"`, or `"unexpected_field"`)
#     - a code using one of these six stage-scoped prefixes but with an
#       empty field suffix is `"malformed_stage_information:<code>"`;
#       any other stage name, kind, or code shape entirely outside
#       Prompt 547's vocabulary (so it can only have been invented,
#       including one that merely resembles a genuine stage or source
#       reference without actually being one) is `"unrecognized_error_
#       code:<code>"`
#   - once `"warnings"` is well-typed, every entry in it is
#     `"fabricated_warning:<code>"` - Prompt 547 never raises a warning
#     of its own, so any warning present was invented
#   - once `"status"` and `"errors"` are each individually well-formed
#     enough to compare, `"status"` is re-derived from the categories
#     of codes present in `"errors"`, by the SAME fixed priority order
#     Prompt 547's own implementation uses (any input-error code present
#     means `"invalid_input"`; else any error present at all means
#     `"inconsistent"`; else `"consistent"`), and must match exactly
#     (`"status_inconsistent_with_errors:<status>"` otherwise) - this is
#     what catches `"consistent"` reported alongside real mismatch
#     evidence, `"inconsistent"` reported with no supporting error, and
#     `"invalid_input"` reported with no input-error code present (or
#     vice versa)
#
# A field that already failed its own type/membership check is left out
# of the cross-field check - there is nothing meaningful to compare
# against, so a single bad field never cascades into extra, misleading
# consistency errors.
#
# `"status"` is `"invalid_input"` only when `result` itself is not a
# `dict` (malformed validation input, `"result_not_a_dict"`) - reserved
# for that case alone, never for a content-level problem inside an
# otherwise well-typed dict. Any content-level problem found above
# yields `"status": "inconsistent"`; no problem found yields `"status":
# "consistent"`. `"warnings"` is always `[]` - this layer raises no
# warnings of its own, only errors.
#
# Reuses the existing Prompt 547 result shape and error-code vocabulary
# throughout; creates no second consistency or validation system, no
# metric, prediction, score, rank, or recommendation. Never mutates
# `result`, never repairs or reinterprets a problem it finds, and never
# changes the stage-order calculation, the stage-order result
# validation, the filtered trend system, or the coverage chain. Not
# called from the gate/decision/response path. Deterministic: the same
# `result` dict always produces an equal validation result, in the same
# order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_RESULT_REQUIRED_FIELDS = (
    "status", "errors", "warnings",
)

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_STATUSES = (
    "consistent", "inconsistent", "invalid_input",
)

# Exact-match error codes `validate_learned_knowledge_filtered_trend_
# source_coverage_chain_stage_order_consistency()` (Prompt 547) can
# produce - each one already means the whole check read "invalid_
# input".
_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_INPUT_ERROR_CODES = (
    "chain_stages_invalid_type",
    "stage_order_invalid_type",
    "order_result_not_a_dict",
    "order_result_validation_not_a_dict",
)

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_STAGE_NAMES = (
    "order_result", "order_result_validation",
)

_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_FIELD_DIFF_KINDS = (
    "missing_field", "mismatched_field", "unexpected_field",
)

# The fixed set of `"stage:<link>:<kind>:"` prefixes Prompt 547's own
# `_filtered_trend_source_coverage_chain_stage_diff()` calls can
# produce for its two links (`"order_result"`, `"order_result_
# validation"`); a matching code must carry a non-empty field suffix
# after one of these.
_FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_PREFIXED_ERROR_CODES = tuple(
    "stage:%s:%s:" % (stage, kind)
    for stage in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_STAGE_NAMES
    for kind in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_FIELD_DIFF_KINDS
)


def _filtered_trend_source_coverage_chain_stage_order_consistency_error_code_problem(code):
    """`None` if `code` is a recognized Prompt 547 error code with
    valid structure, else the specific problem: `"malformed_stage_
    information:<code>"` for a recognized stage-scoped prefix whose
    required field suffix is empty, or `"unrecognized_error_code:
    <code>"` for a code outside Prompt 547's fixed vocabulary entirely
    (including one that merely resembles a genuine stage or source
    reference without being one). Performs no detection of its own
    beyond a shape check of `code`'s own text."""
    if code in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_INPUT_ERROR_CODES:
        return None
    for prefix in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_PREFIXED_ERROR_CODES:
        if code.startswith(prefix):
            if len(code) > len(prefix):
                return None
            return "malformed_stage_information:%s" % code
    return "unrecognized_error_code:%s" % code


def _filtered_trend_source_coverage_chain_stage_order_consistency_expected_status(errors):
    """The Prompt 547 `\"status\"` that the categories of codes present
    in `errors` would justify, derived by the exact same fixed priority
    order `validate_learned_knowledge_filtered_trend_source_coverage_
    chain_stage_order_consistency()` (Prompt 547) itself uses. Reads
    only `errors`; performs no detection of its own and never looks at
    any `chain_stages`/`stage_order`/`order_result`/`order_result_
    validation` input."""
    if any(code in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_INPUT_ERROR_CODES
           for code in errors):
        return "invalid_input"
    if errors:
        return "inconsistent"
    return "consistent"


def validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency_result(result):
    """Deterministic, read-only structural validation of `result` - the
    dict shape `validate_learned_knowledge_filtered_trend_source_
    coverage_chain_stage_order_consistency()` (Prompt 547) returns.
    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `result` given as anything other than a `dict` (including `None`)
    safely reads `"status": "invalid_input"` with `"result_not_a_
    dict"` in `"errors"`, rather than raising - the only case that
    reads `"invalid_input"` here.

    Otherwise this checks `result`'s own fields for missing/mis-typed
    entries, checks every code in `"errors"`/`"warnings"` against
    Prompt 547's fixed error-code vocabulary, and re-derives the
    expected `"status"` from the categories of codes actually present
    in `"errors"` - comparing it against the reported `"status"`. See
    the module note above for every problem this can report; each
    yields `"status": "inconsistent"`. No problem found yields
    `"status": "consistent"`.

    Never re-runs or re-derives anything from Prompt 547's own
    `chain_stages`/`stage_order`/`order_result`/`order_result_
    validation` input, and never calls Prompt 545 or 546 - only
    `result`'s own fields are read. Never repairs, normalizes, or
    otherwise changes `result`, and never mutates it. Not called from
    the gate/decision/response path. Deterministic: the same `result`
    dict always produces an equal validation result, in the same
    order, on every call.
    """
    if not isinstance(result, dict):
        return {"status": "invalid_input", "errors": ["result_not_a_dict"], "warnings": []}

    errors = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_RESULT_REQUIRED_FIELDS:
        if field not in result:
            errors.append("missing_field:%s" % field)

    status_ok = ("status" in result and isinstance(result["status"], str)
                 and result["status"] in _FILTERED_TREND_SOURCE_COVERAGE_CHAIN_STAGE_ORDER_CONSISTENCY_STATUSES)
    if "status" in result and not status_ok:
        errors.append("invalid_status")

    errors_ok = ("errors" in result and isinstance(result["errors"], list)
                 and all(isinstance(code, str) for code in result["errors"]))
    if "errors" in result and not errors_ok:
        errors.append("invalid_type:errors")

    warnings_ok = ("warnings" in result and isinstance(result["warnings"], list)
                   and all(isinstance(code, str) for code in result["warnings"]))
    if "warnings" in result and not warnings_ok:
        errors.append("invalid_type:warnings")

    if errors_ok:
        for code in result["errors"]:
            problem = _filtered_trend_source_coverage_chain_stage_order_consistency_error_code_problem(code)
            if problem is not None:
                errors.append(problem)

    if warnings_ok:
        for code in result["warnings"]:
            errors.append("fabricated_warning:%s" % code)

    if status_ok and errors_ok:
        expected_status = _filtered_trend_source_coverage_chain_stage_order_consistency_expected_status(
            result["errors"])
        if result["status"] != expected_status:
            errors.append("status_inconsistent_with_errors:%s" % result["status"])

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 549 - validate complete filtered trend source coverage chain
# consistency (Prompts 541-548, end to end)
# ----------------------------------------------------------------------
# Prompts 541-548 build an eight-link chain:
#
#   source comparisons -> coverage (541) -> coverage validation (542)
#     -> coverage consistency (543) -> chain integrity validation (544)
#     -> chain stage order (545) -> stage order validation (546)
#     -> stage order consistency (547)
#     -> stage order consistency validation (548)
#
# Two existing validators already tie together every value-level
# relationship in that chain: `validate_learned_knowledge_filtered_
# trend_source_coverage_chain()` (Prompt 544) recomputes 541/542/543 on
# the same inputs a caller already used and compares each against the
# caller's claimed stage results, and `validate_learned_knowledge_
# filtered_trend_source_coverage_chain_stage_order_consistency()`
# (Prompt 547) does the same for 545/546. `validate_learned_knowledge_
# filtered_trend_source_coverage_chain_stage_order_consistency_result()`
# (Prompt 548) is a third, purely structural, check of Prompt 547's own
# result shape. Nothing so far checks that a caller's claimed results
# for ALL EIGHT links - Prompt 544's own chain result, and Prompt 547's
# and 548's own results - correspond to one another and to their shared
# inputs, end to end, in a single call.
#
# `validate_learned_knowledge_filtered_trend_source_coverage_complete_
# chain_consistency()` adds exactly that, and only that: it calls
# Prompt 544, Prompt 547, and Prompt 548 again, unchanged, on the SAME
# inputs the caller already used to reach each claimed stage, and
# compares each recomputation against what the caller claims for that
# stage, field by field, using the same `_filtered_trend_source_
# coverage_chain_stage_diff()` helper Prompts 544 and 547 already use.
# It adds no detection of its own, re-derives nothing 541-548 do not
# already compute, and duplicates none of their algorithms.
#
# Because Prompt 544 itself already recomputes and compares 541, 542,
# and 543, and Prompt 547 itself already recomputes and compares 545
# and 546, this three-way comparison (544, 547, 548) is what verifies
# the complete chain: every stage references the correct previous
# stage, source comparison references and coverage state stay
# consistent with the source data, coverage validation/consistency
# agree with coverage, stage-order information agrees with the
# `chain_stages`/`stage_order` description of the coverage chain,
# stage-order validation agrees with the stage-order result,
# stage-order consistency agrees with the source chain and stage-order
# result, and stage-order consistency validation agrees with the
# consistency result. No stage can silently lose or fabricate
# information, and invalid information at any stage is never silently
# converted into valid information, without a mismatch surfacing on
# the specific link where it was found - a single dict-equality
# comparison on each recomputed field already catches any lost,
# invented, or altered source ID, snapshot ID, comparison ID, or stage
# identifier embedded in that field.
#
# `validate_learned_knowledge_filtered_trend_source_coverage_complete_
# chain_consistency(comparisons, trend_summary, coverage_result,
#      coverage_validation_result, consistency_result, chain_result,
#      chain_stages, stage_order, order_result, order_result_validation,
#      order_result_consistency, order_result_consistency_validation)`:
#
#   - `trend_summary`, `coverage_result`, `coverage_validation_result`,
#     `consistency_result`, `chain_result`, `order_result`,
#     `order_result_validation`, `order_result_consistency`, or
#     `order_result_consistency_validation` given as anything other
#     than a `dict` (including `None`), `comparisons` given as anything
#     other than a `list`, a `tuple`, or `None`, `chain_stages` given as
#     anything other than a `list`/`tuple`, or a given `stage_order`
#     that is not `None` and not a `list`/`tuple` - malformed chain
#     input - reads `"status": "invalid_input"` with one `"<name>_not_
#     a_dict"` / `"comparisons_invalid_type"` / `"chain_stages_invalid_
#     type"` / `"stage_order_invalid_type"` entry per malformed
#     argument, rather than raising. This is the only case this
#     function itself decides is malformed; a `dict` with missing or
#     wrong-shaped fields inside it is instead reported as an ordinary
#     `"inconsistent"` mismatch by the three link checks below (544 and
#     547 already handle a malformed `dict` gracefully without
#     raising, as does 548).
#   - Link 1 (541+542+543 -> chain integrity, Prompt 544): recomputes
#     Prompt 544 on `comparisons`/`trend_summary`/`coverage_result`/
#     `coverage_validation_result`/`consistency_result`, unchanged, and
#     compares it against `chain_result` field by field.
#   - Link 2 (545+546 -> stage order consistency, Prompt 547):
#     recomputes Prompt 547 on `chain_stages`/`stage_order`/
#     `order_result`/`order_result_validation`, unchanged, and compares
#     it against `order_result_consistency` field by field.
#   - Link 3 (stage order consistency -> its own structural validation,
#     Prompt 548): recomputes Prompt 548 on `order_result_consistency`
#     AS GIVEN (not link 2's recomputation - a link 2 mismatch is
#     already reported on its own and never masks or double-counts a
#     link 3 problem), and compares it against `order_result_
#     consistency_validation` field by field.
#   - Each field comparison reports, per field: `"stage:<link>:missing_
#     field:<name>"` for a field the recomputation has but the claimed
#     stage result lacks (information silently dropped), `"stage:
#     <link>:mismatched_field:<name>"` for a field present on both
#     sides with different values (including a `dict`/`list` field, so
#     any lost, invented, or reordered entry inside `"errors"` or
#     `"coverage"` surfaces as a single mismatch on that field), and
#     `"stage:<link>:unexpected_field:<name>"` for a field the claimed
#     stage result has that the recomputation does not (information
#     invented rather than found). `<link>` is one of `"chain"`,
#     `"stage_order_consistency"`, or `"stage_order_consistency_
#     validation"`, so every error names exactly which link of the
#     complete chain it was found on.
#
# `"status"` is `"consistent"` when no link reports a problem, else
# `"inconsistent"` (or `"invalid_input"` for the malformed-argument
# case above, which takes precedence over all three link checks).
# `"warnings"` is always `[]` - this layer raises no warnings of its
# own, only errors - kept in the returned shape so callers have a
# stable envelope regardless of outcome.
#
# Reuses Prompts 544, 547, and 548 exactly as they stand throughout -
# which themselves reuse 541, 542, 543, 545, and 546 exactly as they
# stand - introducing no second coverage, validation, stage-order, or
# chain architecture, no new metric, prediction, score, rank, or
# recommendation. Never repairs, regenerates, or otherwise changes any
# of its twelve arguments, and never mutates any of them. Not called
# from the gate/decision/response path. Deterministic: the same twelve
# arguments always produce an equal result, in the same order, on
# every call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_LINKS = (
    "chain", "stage_order_consistency", "stage_order_consistency_validation",
)


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency(
        comparisons, trend_summary, coverage_result, coverage_validation_result,
        consistency_result, chain_result,
        chain_stages, stage_order, order_result, order_result_validation,
        order_result_consistency, order_result_consistency_validation):
    """Deterministic, read-only check that a caller's claimed results
    for every link of the complete, eight-stage filtered trend source
    coverage validation chain (Prompts 541-548) actually correspond to
    one another and to their shared inputs, end to end.

    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `trend_summary`, `coverage_result`, `coverage_validation_result`,
    `consistency_result`, `chain_result`, `order_result`,
    `order_result_validation`, `order_result_consistency`, or
    `order_result_consistency_validation` given as anything other than
    a `dict` (including `None`), `comparisons` given as anything other
    than a `list`, a `tuple`, or `None`, `chain_stages` given as
    anything other than a `list`/`tuple`, or a given `stage_order` that
    is not `None` and not a `list`/`tuple`, safely reads `"status":
    "invalid_input"` rather than raising, with one `"<name>_not_a_
    dict"` / `"comparisons_invalid_type"` / `"chain_stages_invalid_
    type"` / `"stage_order_invalid_type"` entry per malformed argument.

    Otherwise this recomputes Prompt 544 on `comparisons`/
    `trend_summary`/`coverage_result`/`coverage_validation_result`/
    `consistency_result`, Prompt 547 on `chain_stages`/`stage_order`/
    `order_result`/`order_result_validation`, and Prompt 548 on
    `order_result_consistency` as given - each unchanged - and compares
    each recomputation against the caller's matching claimed result
    field by field. See the module note above for exactly what this
    catches and every error code this can report, each one naming the
    specific chain link (`"chain"`, `"stage_order_consistency"`, or
    `"stage_order_consistency_validation"`) it was found on.

    Never re-runs or re-derives anything beyond calling Prompt 544,
    547, and 548 as they already stand - no second coverage,
    validation, stage-order, or chain system. Never repairs,
    regenerates, or otherwise changes any of its twelve arguments, and
    never mutates any of them. Not called from the gate/decision/
    response path. Deterministic: the same twelve arguments always
    produce an equal result, in the same order, on every call.
    """
    errors = []
    if comparisons is not None and not isinstance(comparisons, (list, tuple)):
        errors.append("comparisons_invalid_type")
    if not isinstance(trend_summary, dict):
        errors.append("trend_summary_not_a_dict")
    if not isinstance(coverage_result, dict):
        errors.append("coverage_result_not_a_dict")
    if not isinstance(coverage_validation_result, dict):
        errors.append("coverage_validation_result_not_a_dict")
    if not isinstance(consistency_result, dict):
        errors.append("consistency_result_not_a_dict")
    if not isinstance(chain_result, dict):
        errors.append("chain_result_not_a_dict")
    if not isinstance(chain_stages, (list, tuple)):
        errors.append("chain_stages_invalid_type")
    if stage_order is not None and not isinstance(stage_order, (list, tuple)):
        errors.append("stage_order_invalid_type")
    if not isinstance(order_result, dict):
        errors.append("order_result_not_a_dict")
    if not isinstance(order_result_validation, dict):
        errors.append("order_result_validation_not_a_dict")
    if not isinstance(order_result_consistency, dict):
        errors.append("order_result_consistency_not_a_dict")
    if not isinstance(order_result_consistency_validation, dict):
        errors.append("order_result_consistency_validation_not_a_dict")
    if errors:
        return {"status": "invalid_input", "errors": errors, "warnings": []}

    errors = []

    expected_chain = validate_learned_knowledge_filtered_trend_source_coverage_chain(
        comparisons, trend_summary, coverage_result, coverage_validation_result, consistency_result)
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_chain, chain_result, "chain"))

    expected_order_consistency = (
        validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency(
            chain_stages, stage_order, order_result, order_result_validation))
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_order_consistency, order_result_consistency, "stage_order_consistency"))

    expected_order_consistency_validation = (
        validate_learned_knowledge_filtered_trend_source_coverage_chain_stage_order_consistency_result(
            order_result_consistency))
    errors.extend(_filtered_trend_source_coverage_chain_stage_diff(
        expected_order_consistency_validation, order_result_consistency_validation,
        "stage_order_consistency_validation"))

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 550 - validate a Prompt 549 complete chain consistency result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check over the dict
# `validate_learned_knowledge_filtered_trend_source_coverage_complete_
# chain_consistency()` (Prompt 549) returns. This is a validator OF
# that result, not a second complete-chain-consistency system: it
# never calls Prompt 549 or anything upstream of it (Prompt 544, 547,
# 548, or the raw `comparisons`/`trend_summary`/`chain_stages`/`stage_
# order`/stage-result inputs), and never repairs, normalizes, or
# otherwise changes the `result` dict it is given - every problem
# found is reported, not fixed. It follows the exact same `{"status",
# "errors", "warnings"}` envelope convention, and the same validator-
# of-a-result shape, that `validate_learned_knowledge_filtered_trend_
# source_coverage_chain_stage_order_result()` (Prompt 546) and
# `validate_learned_knowledge_filtered_trend_source_coverage_chain_
# stage_order_consistency_result()` (Prompt 548) already use.
#
# Everything this validator checks is already fully determined by
# `result`'s own fields:
#
#   - every field in `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_
#     CONSISTENCY_RESULT_REQUIRED_FIELDS` is present (`"missing_field:
#     <n>"` otherwise)
#   - `"status"` is one of the existing Prompt 549
#     `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_
#     STATUSES` (`"invalid_status"` otherwise, whether the value is the
#     wrong type entirely - e.g. a plain `bool` - or simply an
#     unrecognized string)
#   - `"errors"` and `"warnings"` are each a `list` of `str`
#     (`"invalid_type:errors"` / `"invalid_type:warnings"` otherwise)
#   - once `"errors"` is well-typed, every entry in it is checked
#     against Prompt 549's own fixed error-code vocabulary: the twelve
#     exact input-error codes (`"comparisons_invalid_type"`, `"trend_
#     summary_not_a_dict"`, `"coverage_result_not_a_dict"`, `"coverage_
#     validation_result_not_a_dict"`, `"consistency_result_not_a_
#     dict"`, `"chain_result_not_a_dict"`, `"chain_stages_invalid_
#     type"`, `"stage_order_invalid_type"`, `"order_result_not_a_
#     dict"`, `"order_result_validation_not_a_dict"`, `"order_result_
#     consistency_not_a_dict"`, `"order_result_consistency_validation_
#     not_a_dict"`), and the per-link structural-diff codes `"stage:
#     <link>:<kind>:<field>"` (`<link>` being `"chain"`, `"stage_order_
#     consistency"`, or `"stage_order_consistency_validation"`; `<kind>`
#     being `"missing_field"`, `"mismatched_field"`, or `"unexpected_
#     field"`) - a code using one of these nine stage-scoped prefixes
#     but with an empty field suffix is `"malformed_stage_information:
#     <code>"`; any other link name, kind, or code shape entirely
#     outside Prompt 549's vocabulary (so it can only have been
#     invented, including one that merely resembles a genuine link or
#     source reference without actually being one) is `"unrecognized_
#     error_code:<code>"`
#   - once `"warnings"` is well-typed, every entry in it is
#     `"fabricated_warning:<code>"` - Prompt 549 never raises a warning
#     of its own, so any warning present was invented
#   - once `"status"` and `"errors"` are each individually well-formed
#     enough to compare, `"status"` is re-derived from the categories
#     of codes present in `"errors"`, by the SAME fixed priority order
#     Prompt 549's own implementation uses (any input-error code present
#     means `"invalid_input"`; else any error present at all means
#     `"inconsistent"`; else `"consistent"`), and must match exactly
#     (`"status_inconsistent_with_errors:<status>"` otherwise) - this is
#     what catches `"consistent"` reported alongside real mismatch
#     evidence, `"inconsistent"` reported with no supporting error, and
#     `"invalid_input"` reported with no input-error code present (or
#     vice versa)
#
# A field that already failed its own type/membership check is left out
# of the cross-field check - there is nothing meaningful to compare
# against, so a single bad field never cascades into extra, misleading
# consistency errors.
#
# `"status"` is `"invalid_input"` only when `result` itself is not a
# `dict` (malformed validation input, `"result_not_a_dict"`) - reserved
# for that case alone, never for a content-level problem inside an
# otherwise well-typed dict. Any content-level problem found above
# yields `"status": "inconsistent"`; no problem found yields `"status":
# "consistent"`. `"warnings"` is always `[]` - this layer raises no
# warnings of its own, only errors.
#
# Reuses the existing Prompt 549 result shape and error-code vocabulary
# throughout; creates no second consistency or validation system, no
# metric, prediction, score, rank, or recommendation. Never mutates
# `result`, never repairs or reinterprets a problem it finds, and never
# changes the complete-chain-consistency calculation, the coverage
# chain, or the stage-order chain. Not called from the gate/decision/
# response path. Deterministic: the same `result` dict always produces
# an equal validation result, in the same order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_RESULT_REQUIRED_FIELDS = (
    "status", "errors", "warnings",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_STATUSES = (
    "consistent", "inconsistent", "invalid_input",
)

# Exact-match error codes `validate_learned_knowledge_filtered_trend_
# source_coverage_complete_chain_consistency()` (Prompt 549) can
# produce - each one already means the whole check read "invalid_
# input".
_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_INPUT_ERROR_CODES = (
    "comparisons_invalid_type",
    "trend_summary_not_a_dict",
    "coverage_result_not_a_dict",
    "coverage_validation_result_not_a_dict",
    "consistency_result_not_a_dict",
    "chain_result_not_a_dict",
    "chain_stages_invalid_type",
    "stage_order_invalid_type",
    "order_result_not_a_dict",
    "order_result_validation_not_a_dict",
    "order_result_consistency_not_a_dict",
    "order_result_consistency_validation_not_a_dict",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_FIELD_DIFF_KINDS = (
    "missing_field", "mismatched_field", "unexpected_field",
)

# The fixed set of `"stage:<link>:<kind>:"` prefixes Prompt 549's own
# `_filtered_trend_source_coverage_chain_stage_diff()` calls can
# produce for its three links (`"chain"`, `"stage_order_consistency"`,
# `"stage_order_consistency_validation"`); a matching code must carry a
# non-empty field suffix after one of these.
_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_PREFIXED_ERROR_CODES = tuple(
    "stage:%s:%s:" % (link, kind)
    for link in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_LINKS
    for kind in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_FIELD_DIFF_KINDS
)


def _filtered_trend_source_coverage_complete_chain_consistency_error_code_problem(code):
    """`None` if `code` is a recognized Prompt 549 error code with
    valid structure, else the specific problem: `"malformed_stage_
    information:<code>"` for a recognized stage-scoped prefix whose
    required field suffix is empty, or `"unrecognized_error_code:
    <code>"` for a code outside Prompt 549's fixed vocabulary entirely
    (including one that merely resembles a genuine link or source
    reference without being one). Performs no detection of its own
    beyond a shape check of `code`'s own text."""
    if code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_INPUT_ERROR_CODES:
        return None
    for prefix in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_PREFIXED_ERROR_CODES:
        if code.startswith(prefix):
            if len(code) > len(prefix):
                return None
            return "malformed_stage_information:%s" % code
    return "unrecognized_error_code:%s" % code


def _filtered_trend_source_coverage_complete_chain_consistency_expected_status(errors):
    """The Prompt 549 `"status"` that the categories of codes present
    in `errors` would justify, derived by the exact same fixed priority
    order `validate_learned_knowledge_filtered_trend_source_coverage_
    complete_chain_consistency()` (Prompt 549) itself uses. Reads only
    `errors`; performs no detection of its own and never looks at any
    of Prompt 549's own raw inputs."""
    if any(code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_INPUT_ERROR_CODES
           for code in errors):
        return "invalid_input"
    if errors:
        return "inconsistent"
    return "consistent"


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_result(result):
    """Deterministic, read-only structural validation of `result` - the
    dict shape `validate_learned_knowledge_filtered_trend_source_
    coverage_complete_chain_consistency()` (Prompt 549) returns.
    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `result` given as anything other than a `dict` (including `None`)
    safely reads `"status": "invalid_input"` with `"result_not_a_
    dict"` in `"errors"`, rather than raising - the only case that
    reads `"invalid_input"` here.

    Otherwise this checks `result`'s own fields for missing/mis-typed
    entries, checks every code in `"errors"`/`"warnings"` against
    Prompt 549's fixed error-code vocabulary, and re-derives the
    expected `"status"` from the categories of codes actually present
    in `"errors"` - comparing it against the reported `"status"`. See
    the module note above for every problem this can report; each
    yields `"status": "inconsistent"`. No problem found yields
    `"status": "consistent"`.

    Never re-runs or re-derives anything from Prompt 549's own raw
    inputs, and never calls Prompt 544, 547, or 548 - only `result`'s
    own fields are read. Never repairs, normalizes, or otherwise
    changes `result`, and never mutates it. Not called from the gate/
    decision/response path. Deterministic: the same `result` dict
    always produces an equal validation result, in the same order, on
    every call.
    """
    if not isinstance(result, dict):
        return {"status": "invalid_input", "errors": ["result_not_a_dict"], "warnings": []}

    errors = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_RESULT_REQUIRED_FIELDS:
        if field not in result:
            errors.append("missing_field:%s" % field)

    status_ok = ("status" in result and isinstance(result["status"], str)
                 and result["status"] in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_STATUSES)
    if "status" in result and not status_ok:
        errors.append("invalid_status")

    errors_ok = ("errors" in result and isinstance(result["errors"], list)
                 and all(isinstance(code, str) for code in result["errors"]))
    if "errors" in result and not errors_ok:
        errors.append("invalid_type:errors")

    warnings_ok = ("warnings" in result and isinstance(result["warnings"], list)
                   and all(isinstance(code, str) for code in result["warnings"]))
    if "warnings" in result and not warnings_ok:
        errors.append("invalid_type:warnings")

    if errors_ok:
        for code in result["errors"]:
            problem = _filtered_trend_source_coverage_complete_chain_consistency_error_code_problem(code)
            if problem is not None:
                errors.append(problem)

    if warnings_ok:
        for code in result["warnings"]:
            errors.append("fabricated_warning:%s" % code)

    if status_ok and errors_ok:
        expected_status = _filtered_trend_source_coverage_complete_chain_consistency_expected_status(
            result["errors"])
        if result["status"] != expected_status:
            errors.append("status_inconsistent_with_errors:%s" % result["status"])

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 551 - validate consistency between a Prompt 549 result and its
# Prompt 550 validation
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY consistency check tying together:
#
#   - a caller's claimed Prompt 549 result, `consistency_result` (what
#     `validate_learned_knowledge_filtered_trend_source_coverage_
#     complete_chain_consistency()` is supposed to have returned)
#   - a caller's claimed Prompt 550 validation of that same result,
#     `validation_result` (what `validate_learned_knowledge_filtered_
#     trend_source_coverage_complete_chain_consistency_result()` is
#     supposed to have returned for it)
#
# This is a consistency validator BETWEEN two existing results - not a
# new complete-chain algorithm, and not a second Prompt 550 structural-
# validation system. It calls Prompt 550 exactly once, on the caller's
# `consistency_result` as given, unchanged, and never calls Prompt 549
# or anything upstream of it (`comparisons`, `trend_summary`, the
# coverage/order/stage-order results, or any other raw input). It never
# repairs, normalizes, or otherwise changes either dict it is given -
# every disagreement found is reported, not fixed.
#
# Everything this validator checks is fully determined by recomputing
# Prompt 550's own validation of `consistency_result` and comparing it,
# field by field, against the caller-supplied `validation_result`,
# using the same `_filtered_trend_source_coverage_chain_stage_diff()`
# helper every other consistency layer in this chain already uses:
#
#   - `"status"` in the freshly recomputed Prompt 550 validation that is
#     missing, mismatched, or contradicted in `validation_result`
#     surfaces as `"stage:validation_result:missing_field:status"` /
#     `"stage:validation_result:mismatched_field:status"`
#   - the same applies to `"errors"` and `"warnings"` - any lost,
#     invented, or reordered entry inside either list surfaces as a
#     single mismatch on that field, since both are compared by value
#   - any field the caller's `validation_result` carries that the fresh
#     Prompt 550 validation does not is `"stage:validation_result:
#     unexpected_field:<name>"` (information invented rather than found)
#
# This single field-by-field comparison is what catches every
# disagreement the caller could present: a malformed `consistency_
# result` (Prompt 550 itself reports the structural problem as part of
# the fresh recomputation, and any `validation_result` that fails to
# match that recomputation gets flagged here), a `validation_result`
# whose claimed `"status"` does not match what Prompt 550 would
# actually report for this `consistency_result` (an inconsistent
# claimed status), a `validation_result` whose `"errors"`/`"warnings"`
# do not match what Prompt 550 would actually report (inconsistent
# validation evidence, including contradictory error/warning
# information), and any other invented or missing field or nested
# structure.
#
# `consistency_result`/`validation_result` given as anything other than
# a `dict` (including `None`) safely reads `"status": "invalid_input"`
# rather than raising, with one `"consistency_result_not_a_dict"` /
# `"validation_result_not_a_dict"` entry per malformed argument - this
# is the only case that reads `"invalid_input"`. Any content-level
# disagreement found above yields `"status": "inconsistent"`; no
# disagreement found yields `"status": "consistent"`. `"warnings"` is
# always `[]` - this layer raises no warnings of its own, only errors.
#
# Reuses the existing Prompt 549/550 result shapes and Prompt 550's own
# vocabulary throughout (via the fresh recomputation); creates no
# second complete-chain-consistency system, no second structural-
# validation system, no metric, prediction, score, rank,
# recommendation, automatic repair, or automatic mutation. Never
# mutates `consistency_result` or `validation_result`. Not called from
# the gate/decision/response path. Deterministic: the same two
# arguments always produce an equal result, in the same order, on every
# call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_INPUT_ERROR_CODES = (
    "consistency_result_not_a_dict",
    "validation_result_not_a_dict",
)


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_validation(
        consistency_result, validation_result):
    """Deterministic, read-only check that a caller's claimed Prompt 550
    validation `validation_result` actually corresponds to what Prompt
    550 (`validate_learned_knowledge_filtered_trend_source_coverage_
    complete_chain_consistency_result()`) would report for the caller's
    claimed Prompt 549 complete-chain consistency result
    `consistency_result`.

    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `consistency_result` or `validation_result` given as anything other
    than a `dict` (including `None`) safely reads `"status": "invalid_
    input"` rather than raising, with one `"consistency_result_not_a_
    dict"` / `"validation_result_not_a_dict"` entry per malformed
    argument.

    Otherwise this recomputes Prompt 550 on `consistency_result` as
    given, unchanged, and compares that recomputation against the
    caller's `validation_result`, field by field. See the module note
    above for exactly what this catches; every mismatch names the
    `"validation_result"` link it was found on.

    Never re-runs or re-derives anything beyond calling Prompt 550 as
    it already stands - no second complete-chain-consistency system and
    no second structural-validation system - and never calls Prompt 549
    or anything upstream of it. Never repairs, regenerates, or
    otherwise changes either of its two arguments, and never mutates
    either of them. Not called from the gate/decision/response path.
    Deterministic: the same two arguments always produce an equal
    result, in the same order, on every call.
    """
    errors = []
    if not isinstance(consistency_result, dict):
        errors.append("consistency_result_not_a_dict")
    if not isinstance(validation_result, dict):
        errors.append("validation_result_not_a_dict")
    if errors:
        return {"status": "invalid_input", "errors": errors, "warnings": []}

    expected_validation = validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_result(
        consistency_result)

    errors = _filtered_trend_source_coverage_chain_stage_diff(
        expected_validation, validation_result, "validation_result")

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 552 - validate a Prompt 551 consistency-validation result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check over the dict
# `validate_learned_knowledge_filtered_trend_source_coverage_complete_
# chain_consistency_validation()` (Prompt 551) returns. This is a
# validator OF that result, not a second consistency-between-results
# system: it never calls Prompt 551, Prompt 550, Prompt 549, or
# anything upstream of them (`consistency_result`/`validation_result`
# or any raw input), and never repairs, normalizes, or otherwise
# changes the `result` dict it is given - every problem found is
# reported, not fixed. It follows the exact same `{"status", "errors",
# "warnings"}` envelope convention, and the same validator-of-a-result
# shape, that `validate_learned_knowledge_filtered_trend_source_
# coverage_chain_stage_order_consistency_result()` (Prompt 548) and
# `validate_learned_knowledge_filtered_trend_source_coverage_complete_
# chain_consistency_result()` (Prompt 550) already use. Prompt 551's
# result carries no separate evidence/details field beyond `"errors"`/
# `"warnings"` themselves (just like Prompt 549/550's own results), so
# there is nothing further to validate there.
#
# Everything this validator checks is already fully determined by
# `result`'s own fields:
#
#   - every field in `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_
#     CONSISTENCY_VALIDATION_RESULT_REQUIRED_FIELDS` is present
#     (`"missing_field:<n>"` otherwise)
#   - `"status"` is one of the existing Prompt 551
#     `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_
#     VALIDATION_STATUSES` (`"invalid_status"` otherwise, whether the
#     value is the wrong type entirely - e.g. a plain `bool` - or
#     simply an unrecognized string)
#   - `"errors"` and `"warnings"` are each a `list` of `str`
#     (`"invalid_type:errors"` / `"invalid_type:warnings"` otherwise)
#   - once `"errors"` is well-typed, every entry in it is checked
#     against Prompt 551's own fixed error-code vocabulary - reusing
#     Prompt 551's own `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_
#     CONSISTENCY_VALIDATION_INPUT_ERROR_CODES` constant unchanged -
#     the two exact input-error codes (`"consistency_result_not_a_
#     dict"`, `"validation_result_not_a_dict"`), and the single-link
#     structural-diff codes `"stage:validation_result:<kind>:<field>"`
#     (`<kind>` being `"missing_field"`, `"mismatched_field"`, or
#     `"unexpected_field"`) - a code using this stage-scoped prefix but
#     with an empty field suffix is `"malformed_stage_information:
#     <code>"`; any other link name, kind, or code shape entirely
#     outside Prompt 551's vocabulary (so it can only have been
#     invented, including one that merely resembles a genuine link or
#     source reference without actually being one) is `"unrecognized_
#     error_code:<code>"`
#   - once `"warnings"` is well-typed, every entry in it is
#     `"fabricated_warning:<code>"` - Prompt 551 never raises a warning
#     of its own, so any warning present was invented
#   - once `"status"` and `"errors"` are each individually well-formed
#     enough to compare, `"status"` is re-derived from the categories
#     of codes present in `"errors"`, by the SAME fixed priority order
#     Prompt 551's own implementation uses (any input-error code
#     present means `"invalid_input"`; else any error present at all
#     means `"inconsistent"`; else `"consistent"`), and must match
#     exactly (`"status_inconsistent_with_errors:<status>"` otherwise)
#     - this is what catches `"consistent"` reported alongside real
#     mismatch evidence, `"inconsistent"` reported with no supporting
#     error, and `"invalid_input"` reported with no input-error code
#     present (or vice versa)
#
# A field that already failed its own type/membership check is left out
# of the cross-field check - there is nothing meaningful to compare
# against, so a single bad field never cascades into extra, misleading
# consistency errors.
#
# `"status"` is `"invalid_input"` only when `result` itself is not a
# `dict` (malformed validation input, `"result_not_a_dict"`) - reserved
# for that case alone, never for a content-level problem inside an
# otherwise well-typed dict. Any content-level problem found above
# yields `"status": "inconsistent"`; no problem found yields `"status":
# "consistent"`. `"warnings"` is always `[]` - this layer raises no
# warnings of its own, only errors.
#
# Reuses the existing Prompt 551 result shape and error-code vocabulary
# throughout; creates no second consistency-between-results or
# structural-validation system, no metric, prediction, score, rank, or
# recommendation. Never mutates `result`, never repairs or reinterprets
# a problem it finds, and never changes Prompt 549, 550, or 551. Not
# called from the gate/decision/response path. Deterministic: the same
# `result` dict always produces an equal validation result, in the same
# order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_RESULT_REQUIRED_FIELDS = (
    "status", "errors", "warnings",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_STATUSES = (
    "consistent", "inconsistent", "invalid_input",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_LINK_NAMES = (
    "validation_result",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_FIELD_DIFF_KINDS = (
    "missing_field", "mismatched_field", "unexpected_field",
)

# The fixed set of `"stage:<link>:<kind>:"` prefixes Prompt 551's own
# `_filtered_trend_source_coverage_chain_stage_diff()` call can produce
# for its single link (`"validation_result"`); a matching code must
# carry a non-empty field suffix after one of these.
_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_PREFIXED_ERROR_CODES = tuple(
    "stage:%s:%s:" % (link, kind)
    for link in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_LINK_NAMES
    for kind in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_FIELD_DIFF_KINDS
)


def _filtered_trend_source_coverage_complete_chain_consistency_validation_error_code_problem(code):
    """`None` if `code` is a recognized Prompt 551 error code with
    valid structure, else the specific problem: `"malformed_stage_
    information:<code>"` for a recognized stage-scoped prefix whose
    required field suffix is empty, or `"unrecognized_error_code:
    <code>"` for a code outside Prompt 551's fixed vocabulary entirely
    (including one that merely resembles a genuine link or source
    reference without being one). Performs no detection of its own
    beyond a shape check of `code`'s own text. Reuses Prompt 551's own
    `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_
    VALIDATION_INPUT_ERROR_CODES` constant unchanged."""
    if code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_INPUT_ERROR_CODES:
        return None
    for prefix in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_PREFIXED_ERROR_CODES:
        if code.startswith(prefix):
            if len(code) > len(prefix):
                return None
            return "malformed_stage_information:%s" % code
    return "unrecognized_error_code:%s" % code


def _filtered_trend_source_coverage_complete_chain_consistency_validation_expected_status(errors):
    """The Prompt 551 `"status"` that the categories of codes present
    in `errors` would justify, derived by the exact same fixed priority
    order `validate_learned_knowledge_filtered_trend_source_coverage_
    complete_chain_consistency_validation()` (Prompt 551) itself uses.
    Reads only `errors`; performs no detection of its own and never
    looks at any of Prompt 551's own raw inputs."""
    if any(code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_INPUT_ERROR_CODES
           for code in errors):
        return "invalid_input"
    if errors:
        return "inconsistent"
    return "consistent"


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_validation_result(result):
    """Deterministic, read-only structural validation of `result` - the
    dict shape `validate_learned_knowledge_filtered_trend_source_
    coverage_complete_chain_consistency_validation()` (Prompt 551)
    returns. Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `result` given as anything other than a `dict` (including `None`)
    safely reads `"status": "invalid_input"` with `"result_not_a_
    dict"` in `"errors"`, rather than raising - the only case that
    reads `"invalid_input"` here.

    Otherwise this checks `result`'s own fields for missing/mis-typed
    entries, checks every code in `"errors"`/`"warnings"` against
    Prompt 551's fixed error-code vocabulary, and re-derives the
    expected `"status"` from the categories of codes actually present
    in `"errors"` - comparing it against the reported `"status"`. See
    the module note above for every problem this can report; each
    yields `"status": "inconsistent"`. No problem found yields
    `"status": "consistent"`.

    Never re-runs or re-derives anything from Prompt 551's own raw
    inputs, and never calls Prompt 549, 550, or 551 - only `result`'s
    own fields are read. Never repairs, normalizes, or otherwise
    changes `result`, and never mutates it. Not called from the gate/
    decision/response path. Deterministic: the same `result` dict
    always produces an equal validation result, in the same order, on
    every call.
    """
    if not isinstance(result, dict):
        return {"status": "invalid_input", "errors": ["result_not_a_dict"], "warnings": []}

    errors = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_RESULT_REQUIRED_FIELDS:
        if field not in result:
            errors.append("missing_field:%s" % field)

    status_ok = ("status" in result and isinstance(result["status"], str)
                 and result["status"] in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_CONSISTENCY_VALIDATION_STATUSES)
    if "status" in result and not status_ok:
        errors.append("invalid_status")

    errors_ok = ("errors" in result and isinstance(result["errors"], list)
                 and all(isinstance(code, str) for code in result["errors"]))
    if "errors" in result and not errors_ok:
        errors.append("invalid_type:errors")

    warnings_ok = ("warnings" in result and isinstance(result["warnings"], list)
                   and all(isinstance(code, str) for code in result["warnings"]))
    if "warnings" in result and not warnings_ok:
        errors.append("invalid_type:warnings")

    if errors_ok:
        for code in result["errors"]:
            problem = _filtered_trend_source_coverage_complete_chain_consistency_validation_error_code_problem(code)
            if problem is not None:
                errors.append(problem)

    if warnings_ok:
        for code in result["warnings"]:
            errors.append("fabricated_warning:%s" % code)

    if status_ok and errors_ok:
        expected_status = _filtered_trend_source_coverage_complete_chain_consistency_validation_expected_status(
            result["errors"])
        if result["status"] != expected_status:
            errors.append("status_inconsistent_with_errors:%s" % result["status"])

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 553 - validate consistency between a Prompt 551 result and its
# Prompt 552 validation
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY consistency check tying together:
#
#   - a caller's claimed Prompt 551 result, `validation_result` (what
#     `validate_learned_knowledge_filtered_trend_source_coverage_
#     complete_chain_consistency_validation()` is supposed to have
#     returned)
#   - a caller's claimed Prompt 552 validation of that same result,
#     `validation_result_validation` (what `validate_learned_knowledge_
#     filtered_trend_source_coverage_complete_chain_consistency_
#     validation_result()` is supposed to have returned for it)
#
# This is a consistency validator BETWEEN two existing results - not a
# new complete-chain algorithm, and not a second Prompt 552 structural-
# validation system. It calls Prompt 552 exactly once, on the caller's
# `validation_result` as given, unchanged, and never calls Prompt 549,
# 550, or 551, or anything upstream of them (`comparisons`, `trend_
# summary`, the coverage/order/stage-order results, or any other raw
# input). It never repairs, normalizes, or otherwise changes either
# dict it is given - every disagreement found is reported, not fixed.
#
# Everything this validator checks is fully determined by recomputing
# Prompt 552's own validation of `validation_result` and comparing it,
# field by field, against the caller-supplied `validation_result_
# validation`, using the same `_filtered_trend_source_coverage_chain_
# stage_diff()` helper every other consistency layer in this chain
# already uses:
#
#   - `"status"` in the freshly recomputed Prompt 552 validation that is
#     missing, mismatched, or contradicted in `validation_result_
#     validation` surfaces as `"stage:validation_result_validation:
#     missing_field:status"` / `"stage:validation_result_validation:
#     mismatched_field:status"`
#   - the same applies to `"errors"` and `"warnings"` - any lost,
#     invented, or reordered entry inside either list surfaces as a
#     single mismatch on that field, since both are compared by value
#   - any field the caller's `validation_result_validation` carries that
#     the fresh Prompt 552 validation does not is `"stage:validation_
#     result_validation:unexpected_field:<name>"` (information invented
#     rather than found)
#
# This single field-by-field comparison is what catches every
# disagreement the caller could present: a malformed `validation_
# result` (Prompt 552 itself reports the structural problem as part of
# the fresh recomputation, and any `validation_result_validation` that
# fails to match that recomputation gets flagged here), a `validation_
# result_validation` whose claimed `"status"` does not match what
# Prompt 552 would actually report for this `validation_result` (an
# inconsistent claimed status), a `validation_result_validation` whose
# `"errors"`/`"warnings"` do not match what Prompt 552 would actually
# report (inconsistent validation evidence, including contradictory
# error/warning information), and any other invented or missing field
# or nested structure.
#
# `validation_result`/`validation_result_validation` given as anything
# other than a `dict` (including `None`) safely reads `"status":
# "invalid_input"` rather than raising, with one `"validation_result_
# not_a_dict"` / `"validation_result_validation_not_a_dict"` entry per
# malformed argument - this is the only case that reads `"invalid_
# input"`. Any content-level disagreement found above yields `"status":
# "inconsistent"`; no disagreement found yields `"status": "consistent"`.
# `"warnings"` is always `[]` - this layer raises no warnings of its
# own, only errors.
#
# Reuses the existing Prompt 551/552 result shapes and Prompt 552's own
# vocabulary throughout (via the fresh recomputation); creates no
# second complete-chain-consistency system, no second structural-
# validation system, no metric, prediction, score, rank,
# recommendation, automatic repair, or automatic mutation. Never
# mutates `validation_result` or `validation_result_validation`. Not
# called from the gate/decision/response path. Deterministic: the same
# two arguments always produce an equal result, in the same order, on
# every call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_INPUT_ERROR_CODES = (
    "validation_result_not_a_dict",
    "validation_result_validation_not_a_dict",
)


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_validation_consistency(
        validation_result, validation_result_validation):
    """Deterministic, read-only check that a caller's claimed Prompt 552
    validation `validation_result_validation` actually corresponds to
    what Prompt 552 (`validate_learned_knowledge_filtered_trend_source_
    coverage_complete_chain_consistency_validation_result()`) would
    report for the caller's claimed Prompt 551 complete-chain
    consistency-validation result `validation_result`.

    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `validation_result` or `validation_result_validation` given as
    anything other than a `dict` (including `None`) safely reads
    `"status": "invalid_input"` rather than raising, with one
    `"validation_result_not_a_dict"` / `"validation_result_validation_
    not_a_dict"` entry per malformed argument.

    Otherwise this recomputes Prompt 552 on `validation_result` as
    given, unchanged, and compares that recomputation against the
    caller's `validation_result_validation`, field by field. See the
    module note above for exactly what this catches; every mismatch
    names the `"validation_result_validation"` link it was found on.

    Never re-runs or re-derives anything beyond calling Prompt 552 as
    it already stands - no second complete-chain-consistency system and
    no second structural-validation system - and never calls Prompt
    549, 550, or 551, or anything upstream of them. Never repairs,
    regenerates, or otherwise changes either of its two arguments, and
    never mutates either of them. Not called from the gate/decision/
    response path. Deterministic: the same two arguments always
    produce an equal result, in the same order, on every call.
    """
    errors = []
    if not isinstance(validation_result, dict):
        errors.append("validation_result_not_a_dict")
    if not isinstance(validation_result_validation, dict):
        errors.append("validation_result_validation_not_a_dict")
    if errors:
        return {"status": "invalid_input", "errors": errors, "warnings": []}

    expected_validation = validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_consistency_validation_result(
        validation_result)

    errors = _filtered_trend_source_coverage_chain_stage_diff(
        expected_validation, validation_result_validation, "validation_result_validation")

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 554 - validate a Prompt 553 validation-consistency result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural validator of `result` -
# the dict shape `validate_learned_knowledge_filtered_trend_source_
# coverage_complete_chain_validation_consistency()` (Prompt 553)
# returns. This is a validator OF that result, not a second consistency
# system: it never calls Prompt 553, Prompt 552, Prompt 551, or
# anything upstream of them - only `result`'s own fields are read.
#
# Follows the exact same envelope convention Prompt 550/552 (and every
# other structural result validator in this chain) already use, and the
# same `{"status", "errors", "warnings"}` shape `validate_learned_
# knowledge_filtered_trend_source_coverage_complete_chain_consistency_
# validation_result()` (Prompt 552) uses. `result`'s content is itself
# expected to follow Prompt 553's own envelope - `{"status", "errors",
# "warnings"}` - so this validator checks:
#
#   - `"status"` is one of the existing Prompt 553 statuses
#     (`"consistent"`, `"inconsistent"`, `"invalid_input"`) - missing or
#     mis-typed is reported, and a value outside that fixed vocabulary
#     is `"invalid_status"`
#   - `"errors"` is a list of strings, each checked against Prompt 553's
#     own fixed error-code vocabulary - reusing Prompt 553's own
#     `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_
#     CONSISTENCY_INPUT_ERROR_CODES` constant and its single
#     `"validation_result_validation"` stage-diff link unchanged; a
#     recognized stage-scoped prefix (`"stage:validation_result_
#     validation:<kind>:"`) with an empty field suffix is `"malformed_
#     stage_information:<code>"`; anything else outside Prompt 553's
#     vocabulary (so it can only have been invented, not genuinely
#     produced by Prompt 553) is `"unrecognized_error_code:<code>"`
#   - `"warnings"` is a list of strings - since Prompt 553 never raises
#     a warning of its own, any entry present at all is
#     `"fabricated_warning:<code>"` - Prompt 553 never raises a warning
#     for this validator to have legitimately reused
#   - the reported `"status"` is cross-checked against what the
#     categories of codes actually present in `"errors"` would justify,
#     using the exact same fixed priority order Prompt 553's own
#     implementation uses (any input-error code present forces
#     `"invalid_input"`; any other error forces `"inconsistent"`; no
#     error at all means `"consistent"`) - disagreement is `"status_
#     inconsistent_with_errors:<status>"`
#
# `result` given as anything other than a `dict` (including `None`)
# safely reads `"status": "invalid_input"` with `"result_not_a_dict"`
# in `"errors"`, rather than raising - the only case that reads
# `"invalid_input"` here. Any structural problem found above yields
# `"status": "inconsistent"` (this validator's own status, describing
# the structural-validity finding about `result` - distinct from
# `result`'s own `"status"` field); no problem found yields `"status":
# "consistent"`. `"warnings"` is always `[]` - this layer raises no
# warnings of its own, only errors.
#
# Reuses the existing Prompt 553 result shape and error-code vocabulary
# throughout; creates no second consistency-between-results or
# structural-validation system, no metric, prediction, score, rank, or
# recommendation. Never mutates `result`, never repairs or reinterprets
# a problem it finds, and never changes Prompt 549, 550, 551, 552, or
# 553. Not called from the gate/decision/response path. Deterministic:
# the same `result` dict always produces an equal validation result, in
# the same order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_REQUIRED_FIELDS = (
    "status", "errors", "warnings",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_STATUSES = (
    "consistent", "inconsistent", "invalid_input",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_LINK_NAMES = (
    "validation_result_validation",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_FIELD_DIFF_KINDS = (
    "missing_field", "mismatched_field", "unexpected_field",
)

# The fixed set of `"stage:<link>:<kind>:"` prefixes Prompt 553's own
# `_filtered_trend_source_coverage_chain_stage_diff()` call can produce
# for its single link (`"validation_result_validation"`); a matching
# code must carry a non-empty field suffix after one of these.
_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_PREFIXED_ERROR_CODES = tuple(
    "stage:%s:%s:" % (link, kind)
    for link in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_LINK_NAMES
    for kind in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_FIELD_DIFF_KINDS
)


def _filtered_trend_source_coverage_complete_chain_validation_consistency_error_code_problem(code):
    """`None` if `code` is a recognized Prompt 553 error code with
    valid structure, else the specific problem: `"malformed_stage_
    information:<code>"` for a recognized stage-scoped prefix whose
    required field suffix is empty, or `"unrecognized_error_code:
    <code>"` for a code outside Prompt 553's fixed vocabulary entirely
    (including one that merely resembles a genuine link or source
    reference without being one). Performs no detection of its own
    beyond a shape check of `code`'s own text. Reuses Prompt 553's own
    `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_
    CONSISTENCY_INPUT_ERROR_CODES` constant unchanged."""
    if code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_INPUT_ERROR_CODES:
        return None
    for prefix in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_PREFIXED_ERROR_CODES:
        if code.startswith(prefix):
            if len(code) > len(prefix):
                return None
            return "malformed_stage_information:%s" % code
    return "unrecognized_error_code:%s" % code


def _filtered_trend_source_coverage_complete_chain_validation_consistency_expected_status(errors):
    """The Prompt 553 `"status"` that the categories of codes present
    in `errors` would justify, derived by the exact same fixed priority
    order `validate_learned_knowledge_filtered_trend_source_coverage_
    complete_chain_validation_consistency()` (Prompt 553) itself uses.
    Reads only `errors`; performs no detection of its own and never
    looks at any of Prompt 553's own raw inputs."""
    if any(code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_INPUT_ERROR_CODES
           for code in errors):
        return "invalid_input"
    if errors:
        return "inconsistent"
    return "consistent"


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_validation_consistency_result(result):
    """Deterministic, read-only structural validation of `result` - the
    dict shape `validate_learned_knowledge_filtered_trend_source_
    coverage_complete_chain_validation_consistency()` (Prompt 553)
    returns. Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `result` given as anything other than a `dict` (including `None`)
    safely reads `"status": "invalid_input"` with `"result_not_a_
    dict"` in `"errors"`, rather than raising - the only case that
    reads `"invalid_input"` here.

    Otherwise this checks `result`'s own fields for missing/mis-typed
    entries, checks every code in `"errors"`/`"warnings"` against
    Prompt 553's fixed error-code vocabulary, and re-derives the
    expected `"status"` from the categories of codes actually present
    in `"errors"` - comparing it against the reported `"status"`. See
    the module note above for every problem this can report; each
    yields `"status": "inconsistent"`. No problem found yields
    `"status": "consistent"`.

    Never re-runs or re-derives anything from Prompt 553's own raw
    inputs, and never calls Prompt 549, 550, 551, 552, or 553 - only
    `result`'s own fields are read. Never repairs, normalizes, or
    otherwise changes `result`, and never mutates it. Not called from
    the gate/decision/response path. Deterministic: the same `result`
    dict always produces an equal validation result, in the same
    order, on every call.
    """
    if not isinstance(result, dict):
        return {"status": "invalid_input", "errors": ["result_not_a_dict"], "warnings": []}

    errors = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_REQUIRED_FIELDS:
        if field not in result:
            errors.append("missing_field:%s" % field)

    status_ok = ("status" in result and isinstance(result["status"], str)
                 and result["status"] in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_STATUSES)
    if "status" in result and not status_ok:
        errors.append("invalid_status")

    errors_ok = ("errors" in result and isinstance(result["errors"], list)
                 and all(isinstance(code, str) for code in result["errors"]))
    if "errors" in result and not errors_ok:
        errors.append("invalid_type:errors")

    warnings_ok = ("warnings" in result and isinstance(result["warnings"], list)
                   and all(isinstance(code, str) for code in result["warnings"]))
    if "warnings" in result and not warnings_ok:
        errors.append("invalid_type:warnings")

    if errors_ok:
        for code in result["errors"]:
            problem = _filtered_trend_source_coverage_complete_chain_validation_consistency_error_code_problem(code)
            if problem is not None:
                errors.append(problem)

    if warnings_ok:
        for code in result["warnings"]:
            errors.append("fabricated_warning:%s" % code)

    if status_ok and errors_ok:
        expected_status = _filtered_trend_source_coverage_complete_chain_validation_consistency_expected_status(
            result["errors"])
        if result["status"] != expected_status:
            errors.append("status_inconsistent_with_errors:%s" % result["status"])

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 555 - validate consistency between a Prompt 553 result and its
# Prompt 554 validation
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY consistency check tying together:
#
#   - a caller's claimed Prompt 553 result, `consistency_result` (what
#     `validate_learned_knowledge_filtered_trend_source_coverage_
#     complete_chain_validation_consistency()` is supposed to have
#     returned)
#   - a caller's claimed Prompt 554 validation of that same result,
#     `consistency_result_validation` (what `validate_learned_
#     knowledge_filtered_trend_source_coverage_complete_chain_
#     validation_consistency_result()` is supposed to have returned
#     for it)
#
# This is a consistency validator BETWEEN two existing results - not a
# new complete-chain algorithm, and not a second Prompt 554 structural-
# validation system. It calls Prompt 554 exactly once, on the caller's
# `consistency_result` as given, unchanged, and never calls Prompt 549,
# 550, 551, 552, or 553, or anything upstream of them (`comparisons`,
# `trend_summary`, the coverage/order/stage-order results, or any other
# raw input). It never repairs, normalizes, or otherwise changes either
# dict it is given - every disagreement found is reported, not fixed.
#
# Everything this validator checks is fully determined by recomputing
# Prompt 554's own validation of `consistency_result` and comparing it,
# field by field, against the caller-supplied `consistency_result_
# validation`, using the same `_filtered_trend_source_coverage_chain_
# stage_diff()` helper every other consistency layer in this chain
# already uses:
#
#   - `"status"` in the freshly recomputed Prompt 554 validation that is
#     missing, mismatched, or contradicted in `consistency_result_
#     validation` surfaces as `"stage:consistency_result_validation:
#     missing_field:status"` / `"stage:consistency_result_validation:
#     mismatched_field:status"`
#   - the same applies to `"errors"` and `"warnings"` - any lost,
#     invented, or reordered entry inside either list surfaces as a
#     single mismatch on that field, since both are compared by value
#   - any field the caller's `consistency_result_validation` carries
#     that the fresh Prompt 554 validation does not is `"stage:
#     consistency_result_validation:unexpected_field:<name>"`
#     (information invented rather than found)
#
# This single field-by-field comparison is what catches every
# disagreement the caller could present: a malformed `consistency_
# result` (Prompt 554 itself reports the structural problem as part of
# the fresh recomputation, and any `consistency_result_validation` that
# fails to match that recomputation gets flagged here), a `consistency_
# result_validation` whose claimed `"status"` does not match what
# Prompt 554 would actually report for this `consistency_result` (an
# inconsistent claimed status), a `consistency_result_validation` whose
# `"errors"`/`"warnings"` do not match what Prompt 554 would actually
# report (inconsistent validation evidence, including contradictory
# error/warning information), and any other invented or missing field
# or nested structure.
#
# `consistency_result`/`consistency_result_validation` given as
# anything other than a `dict` (including `None`) safely reads
# `"status": "invalid_input"` rather than raising, with one
# `"consistency_result_not_a_dict"` / `"consistency_result_validation_
# not_a_dict"` entry per malformed argument - this is the only case
# that reads `"invalid_input"`, and malformed structures are never
# compared further once found. Any content-level disagreement found
# above yields `"status": "inconsistent"`; no disagreement found yields
# `"status": "consistent"`. `"warnings"` is always `[]` - this layer
# raises no warnings of its own, only errors.
#
# Reuses the existing Prompt 553/554 result shapes and Prompt 554's own
# vocabulary throughout (via the fresh recomputation); creates no
# second complete-chain-consistency system, no second structural-
# validation system, no metric, prediction, score, rank,
# recommendation, automatic repair, or automatic mutation. Never
# mutates `consistency_result` or `consistency_result_validation`. Not
# called from the gate/decision/response path. Deterministic: the same
# two arguments always produce an equal result, in the same order, on
# every call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_INPUT_ERROR_CODES = (
    "consistency_result_not_a_dict",
    "consistency_result_validation_not_a_dict",
)


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_validation_consistency_result_consistency(
        consistency_result, consistency_result_validation):
    """Deterministic, read-only check that a caller's claimed Prompt 554
    validation `consistency_result_validation` actually corresponds to
    what Prompt 554 (`validate_learned_knowledge_filtered_trend_source_
    coverage_complete_chain_validation_consistency_result()`) would
    report for the caller's claimed Prompt 553 complete-chain
    validation-consistency result `consistency_result`.

    Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `consistency_result` or `consistency_result_validation` given as
    anything other than a `dict` (including `None`) safely reads
    `"status": "invalid_input"` rather than raising, with one
    `"consistency_result_not_a_dict"` / `"consistency_result_
    validation_not_a_dict"` entry per malformed argument - checked, and
    returned, before any comparison is attempted.

    Otherwise this recomputes Prompt 554 on `consistency_result` as
    given, unchanged, and compares that recomputation against the
    caller's `consistency_result_validation`, field by field. See the
    module note above for exactly what this catches; every mismatch
    names the `"consistency_result_validation"` link it was found on.

    Never re-runs or re-derives anything beyond calling Prompt 554 as
    it already stands - no second complete-chain-consistency system and
    no second structural-validation system - and never calls Prompt
    549, 550, 551, 552, or 553, or anything upstream of them. Never
    repairs, regenerates, or otherwise changes either of its two
    arguments, and never mutates either of them. Not called from the
    gate/decision/response path. Deterministic: the same two arguments
    always produce an equal result, in the same order, on every call.
    """
    errors = []
    if not isinstance(consistency_result, dict):
        errors.append("consistency_result_not_a_dict")
    if not isinstance(consistency_result_validation, dict):
        errors.append("consistency_result_validation_not_a_dict")
    if errors:
        return {"status": "invalid_input", "errors": errors, "warnings": []}

    expected_validation = validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_validation_consistency_result(
        consistency_result)

    errors = _filtered_trend_source_coverage_chain_stage_diff(
        expected_validation, consistency_result_validation, "consistency_result_validation")

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}


# ----------------------------------------------------------------------
# Prompt 556 - validate a Prompt 555 result-consistency result
# ----------------------------------------------------------------------
# A small, deterministic, READ-ONLY structural check over the dict
# `validate_learned_knowledge_filtered_trend_source_coverage_complete_
# chain_validation_consistency_result_consistency()` (Prompt 555)
# returns. This is a validator OF that result, not a second
# consistency-between-results system: it never calls Prompt 555, 554,
# 553, or anything upstream of them (`consistency_result`/`consistency_
# result_validation` or any raw input), and never repairs, normalizes,
# or otherwise changes the `result` dict it is given - every problem
# found is reported, not fixed. It follows the exact same `{"status",
# "errors", "warnings"}` envelope convention, and the same
# validator-of-a-result shape, that `validate_learned_knowledge_
# filtered_trend_source_coverage_chain_stage_order_consistency_result()`
# (Prompt 548) and `validate_learned_knowledge_filtered_trend_source_
# coverage_complete_chain_consistency_validation_result()` (Prompt 552)
# already use. Prompt 555's result carries no separate evidence/details
# field beyond `"errors"`/`"warnings"` themselves (just like every
# earlier consistency-between-results result in this chain), so there
# is nothing further to validate there.
#
# Everything this validator checks is already fully determined by
# `result`'s own fields:
#
#   - every field in `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_
#     VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_RESULT_REQUIRED_FIELDS`
#     is present (`"missing_field:<n>"` otherwise)
#   - `"status"` is one of the existing Prompt 555
#     `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_
#     CONSISTENCY_RESULT_CONSISTENCY_STATUSES` (`"invalid_status"`
#     otherwise, whether the value is the wrong type entirely - e.g. a
#     plain `bool` - or simply an unrecognized string)
#   - `"errors"` and `"warnings"` are each a `list` of `str`
#     (`"invalid_type:errors"` / `"invalid_type:warnings"` otherwise)
#   - once `"errors"` is well-typed, every entry in it is checked
#     against Prompt 555's own fixed error-code vocabulary - reusing
#     Prompt 555's own `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_
#     VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_INPUT_ERROR_CODES`
#     constant unchanged - the two exact input-error codes
#     (`"consistency_result_not_a_dict"`, `"consistency_result_
#     validation_not_a_dict"`), and the single-link structural-diff
#     codes `"stage:consistency_result_validation:<kind>:<field>"`
#     (`<kind>` being `"missing_field"`, `"mismatched_field"`, or
#     `"unexpected_field"`) - a code using this stage-scoped prefix but
#     with an empty field suffix is `"malformed_stage_information:
#     <code>"`; any other link name, kind, or code shape entirely
#     outside Prompt 555's vocabulary (so it can only have been
#     invented, including one that merely resembles a genuine link or
#     source reference without actually being one) is `"unrecognized_
#     error_code:<code>"`
#   - once `"warnings"` is well-typed, every entry in it is
#     `"fabricated_warning:<code>"` - Prompt 555 never raises a warning
#     of its own, so any warning present was invented
#   - once `"status"` and `"errors"` are each individually well-formed
#     enough to compare, `"status"` is re-derived from the categories
#     of codes present in `"errors"`, by the SAME fixed priority order
#     Prompt 555's own implementation uses (any input-error code
#     present means `"invalid_input"`; else any error present at all
#     means `"inconsistent"`; else `"consistent"`), and must match
#     exactly (`"status_inconsistent_with_errors:<status>"` otherwise)
#     - this is what catches `"consistent"` reported alongside real
#     mismatch evidence, `"inconsistent"` reported with no supporting
#     error, and `"invalid_input"` reported with no input-error code
#     present (or vice versa)
#
# A field that already failed its own type/membership check is left out
# of the cross-field check - there is nothing meaningful to compare
# against, so a single bad field never cascades into extra, misleading
# consistency errors.
#
# `"status"` is `"invalid_input"` only when `result` itself is not a
# `dict` (malformed validation input, `"result_not_a_dict"`) - reserved
# for that case alone, never for a content-level problem inside an
# otherwise well-typed dict. Any content-level problem found above
# yields `"status": "inconsistent"`; no problem found yields `"status":
# "consistent"`. `"warnings"` is always `[]` - this layer raises no
# warnings of its own, only errors.
#
# Reuses the existing Prompt 555 result shape and error-code vocabulary
# throughout; creates no second consistency-between-results or
# structural-validation system, no metric, prediction, score, rank, or
# recommendation. Never mutates `result`, never repairs or reinterprets
# a problem it finds, and never changes Prompt 553, 554, or 555. Not
# called from the gate/decision/response path. Deterministic: the same
# `result` dict always produces an equal validation result, in the same
# order, on every call.

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_RESULT_REQUIRED_FIELDS = (
    "status", "errors", "warnings",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_STATUSES = (
    "consistent", "inconsistent", "invalid_input",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_LINK_NAMES = (
    "consistency_result_validation",
)

_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_FIELD_DIFF_KINDS = (
    "missing_field", "mismatched_field", "unexpected_field",
)

# The fixed set of `"stage:<link>:<kind>:"` prefixes Prompt 555's own
# `_filtered_trend_source_coverage_chain_stage_diff()` call can produce
# for its single link (`"consistency_result_validation"`); a matching
# code must carry a non-empty field suffix after one of these.
_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_PREFIXED_ERROR_CODES = tuple(
    "stage:%s:%s:" % (link, kind)
    for link in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_LINK_NAMES
    for kind in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_FIELD_DIFF_KINDS
)


def _filtered_trend_source_coverage_complete_chain_validation_consistency_result_consistency_error_code_problem(code):
    """`None` if `code` is a recognized Prompt 555 error code with
    valid structure, else the specific problem: `"malformed_stage_
    information:<code>"` for a recognized stage-scoped prefix whose
    required field suffix is empty, or `"unrecognized_error_code:
    <code>"` for a code outside Prompt 555's fixed vocabulary entirely
    (including one that merely resembles a genuine link or source
    reference without being one). Performs no detection of its own
    beyond a shape check of `code`'s own text. Reuses Prompt 555's own
    `_FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_
    CONSISTENCY_RESULT_CONSISTENCY_INPUT_ERROR_CODES` constant
    unchanged."""
    if code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_INPUT_ERROR_CODES:
        return None
    for prefix in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_PREFIXED_ERROR_CODES:
        if code.startswith(prefix):
            if len(code) > len(prefix):
                return None
            return "malformed_stage_information:%s" % code
    return "unrecognized_error_code:%s" % code


def _filtered_trend_source_coverage_complete_chain_validation_consistency_result_consistency_expected_status(errors):
    """The Prompt 555 `"status"` that the categories of codes present
    in `errors` would justify, derived by the exact same fixed priority
    order `validate_learned_knowledge_filtered_trend_source_coverage_
    complete_chain_validation_consistency_result_consistency()`
    (Prompt 555) itself uses. Reads only `errors`; performs no
    detection of its own and never looks at any of Prompt 555's own raw
    inputs."""
    if any(code in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_INPUT_ERROR_CODES
           for code in errors):
        return "invalid_input"
    if errors:
        return "inconsistent"
    return "consistent"


def validate_learned_knowledge_filtered_trend_source_coverage_complete_chain_validation_consistency_result_consistency_result(result):
    """Deterministic, read-only structural validation of `result` - the
    dict shape `validate_learned_knowledge_filtered_trend_source_
    coverage_complete_chain_validation_consistency_result_consistency()`
    (Prompt 555) returns. Returns a new, independent plain dict:

        {
            "status": <"consistent" | "inconsistent" | "invalid_input">,
            "errors": [<str>, ...],
            "warnings": [],
        }

    `result` given as anything other than a `dict` (including `None`)
    safely reads `"status": "invalid_input"` with `"result_not_a_
    dict"` in `"errors"`, rather than raising - the only case that
    reads `"invalid_input"` here.

    Otherwise this checks `result`'s own fields for missing/mis-typed
    entries, checks every code in `"errors"`/`"warnings"` against
    Prompt 555's fixed error-code vocabulary, and re-derives the
    expected `"status"` from the categories of codes actually present
    in `"errors"` - comparing it against the reported `"status"`. See
    the module note above for every problem this can report; each
    yields `"status": "inconsistent"`. No problem found yields
    `"status": "consistent"`.

    Never re-runs or re-derives anything from Prompt 555's own
    `consistency_result`/`consistency_result_validation` input, and
    never calls Prompt 553 or 554 - only `result`'s own fields are
    read. Never repairs, normalizes, or otherwise changes `result`, and
    never mutates it. Not called from the gate/decision/response path.
    Deterministic: the same `result` dict always produces an equal
    validation result, in the same order, on every call.
    """
    if not isinstance(result, dict):
        return {"status": "invalid_input", "errors": ["result_not_a_dict"], "warnings": []}

    errors = []

    for field in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_RESULT_REQUIRED_FIELDS:
        if field not in result:
            errors.append("missing_field:%s" % field)

    status_ok = ("status" in result and isinstance(result["status"], str)
                 and result["status"] in _FILTERED_TREND_SOURCE_COVERAGE_COMPLETE_CHAIN_VALIDATION_CONSISTENCY_RESULT_CONSISTENCY_STATUSES)
    if "status" in result and not status_ok:
        errors.append("invalid_status")

    errors_ok = ("errors" in result and isinstance(result["errors"], list)
                 and all(isinstance(code, str) for code in result["errors"]))
    if "errors" in result and not errors_ok:
        errors.append("invalid_type:errors")

    warnings_ok = ("warnings" in result and isinstance(result["warnings"], list)
                   and all(isinstance(code, str) for code in result["warnings"]))
    if "warnings" in result and not warnings_ok:
        errors.append("invalid_type:warnings")

    if errors_ok:
        for code in result["errors"]:
            problem = _filtered_trend_source_coverage_complete_chain_validation_consistency_result_consistency_error_code_problem(code)
            if problem is not None:
                errors.append(problem)

    if warnings_ok:
        for code in result["warnings"]:
            errors.append("fabricated_warning:%s" % code)

    if status_ok and errors_ok:
        expected_status = _filtered_trend_source_coverage_complete_chain_validation_consistency_result_consistency_expected_status(
            result["errors"])
        if result["status"] != expected_status:
            errors.append("status_inconsistent_with_errors:%s" % result["status"])

    return {"status": "consistent" if not errors else "inconsistent", "errors": errors, "warnings": []}
