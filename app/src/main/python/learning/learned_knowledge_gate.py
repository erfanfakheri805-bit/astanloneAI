"""
Learned Knowledge Gate
========================
Prompt 502. The relevance + reliability gate between Prompt 501's
selection of a directly relevant learned-knowledge entry and its
insertion into the response-generation context:

    Core._attach_learned_knowledge()
      -> select_learned_knowledge()            (Prompt 501: exactly one
                                                directly relevant entry)
      -> evaluate_learned_knowledge_gate()     (THIS MODULE)
      -> understanding.learned_knowledge_context   only when PASSED

Nothing new is learned, stored or scored here, and no parallel learning
system is introduced. The gate reuses what the project already has:

    relevance     the entry must still be directly relevant: its stored
                  name equals the lookup term that selected it (same
                  case-insensitive, whitespace-collapsed comparison the
                  KnowledgeSystem's own name lookup uses) AND that term
                  really occurs, as consecutive whole words, in the
                  user's message (same word definition as
                  understanding/term_extraction.py).
    reliability   `LearningAnalyzer` (learning/learning_analyzer.py) -
                  the stored evidence for the entry is expressed as
                  `LearningRecord`s (learning/learning_record.py) and
                  judged by the analyzer's own `get_pattern_report()` /
                  `is_pattern_reliable()`: enough valid records, and an
                  average confidence at or above the analyzer's existing
                  default threshold (0.7).

The evidence for one entry
--------------------------
    * the entry's own stored `confidence`, when the entry carries a
      non-blank `description` (a bare stub's confidence says nothing
      about any learned content - stubs are always stored at 1.0);
    * the stored `confidence` of every relationship (outgoing and
      incoming) the entry takes part in.
Each becomes one `LearningRecord(pattern=<entry name>, outcome="success",
confidence=<stored confidence>)` - "success" because a stored assertion
is a positive observation, not an execution failure. A stored
confidence of None means "the teacher gave none": the existing
KnowledgeSystem policy (`learn()` defaults a new entry to 1.0) is
followed, so explicitly taught facts without a stated confidence (for
example AEL `TEACH` / `RELATE`, whose behavior is untouched) stay
usable. A confidence that is not a number in [0.0, 1.0] makes its
record invalid, so the analyzer ignores it - an entry with no valid
evidence is rejected.

`MIN_SUPPORTING_RECORDS` is 1, not the analyzer's default of 2: one
explicitly taught fact is a complete piece of learned knowledge, and
requiring two would make every singly-taught fact (Prompt 501's whole
use case) unusable.

Results
-------
PASSED  the entry may continue through the Prompt 501 path unchanged.
REJECTED  it may not: nothing is injected, nothing is fabricated in its
        place, the request is never touched, and the existing response
        behavior continues. `reason` is one of the REASON_* codes below.

Deterministic, read-only, never raises: any unexpected problem is a
REJECTED result (REASON_GATE_ERROR). Nothing passed in is mutated.

Decision trace (Prompt 503)
----------------------------
`build_learned_knowledge_gate_trace()` turns an already-computed
`LearnedKnowledgeGateResult` into a small structured
`LearnedKnowledgeGateTrace` for later internal analysis - e.g. "why was
this rejected". It is purely descriptive: it reads the result's own
`status`/`reason`/`supporting_records`/`average_confidence`/
`success_rate`/`min_confidence` fields, calls nothing (no analyzer, no
relevance re-check), and cannot change what the gate decided - the
decision and its rejection reason (when rejected) were already fixed by
`evaluate_learned_knowledge_gate()` before the trace is built. It is
internal-only: nothing about it is inserted into a response or shown to
the user, and building one never touches `selection` or `message`.
"""

import copy
import re

from .learning_analyzer import LearningAnalyzer
from .learning_record import LearningRecord

STATUS_PASSED = "PASSED"
STATUS_REJECTED = "REJECTED"

REASON_OK = "ok"
REASON_NOT_SELECTED = "not_selected"
REASON_NOT_RELEVANT = "not_relevant"
REASON_NO_EVIDENCE = "no_supporting_evidence"
REASON_INSUFFICIENT_RELIABILITY = "insufficient_reliability"
REASON_GATE_ERROR = "gate_error"

# The LearningAnalyzer's own default reliability threshold
# (`is_pattern_reliable(..., min_confidence=0.7)`).
MIN_RELIABLE_CONFIDENCE = 0.7
# See the module docstring: one explicitly taught fact is enough evidence.
MIN_SUPPORTING_RECORDS = 1

_WORD_RE = re.compile(r"[A-Za-z0-9_']+")
_OUTCOME_SUCCESS = "success"
_DEFAULT_SOURCE = "knowledge"


class LearnedKnowledgeGateResult:
    """Plain, read-only verdict - same value-holder conventions as the
    rest of learning/ (a `to_dict()`, never validating by raising)."""

    def __init__(self, status, reason, detail="", supporting_records=0,
                 average_confidence=0.0, success_rate=0.0,
                 min_confidence=MIN_RELIABLE_CONFIDENCE):
        self.status = status
        self.reason = reason
        self.detail = detail
        self.supporting_records = supporting_records
        self.average_confidence = average_confidence
        self.success_rate = success_rate
        self.min_confidence = min_confidence

    @property
    def passed(self):
        return self.status == STATUS_PASSED

    def __repr__(self):
        return f"LearnedKnowledgeGateResult(status={self.status!r}, reason={self.reason!r})"

    def to_dict(self):
        return {
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
            "supporting_records": self.supporting_records,
            "average_confidence": self.average_confidence,
            "success_rate": self.success_rate,
            "min_confidence": self.min_confidence,
        }


# ----------------------------------------------------------------------
# Prompt 503: structured decision trace for an already-computed result.
# ----------------------------------------------------------------------

DECISION_ACCEPTED = "accepted"
DECISION_REJECTED_IRRELEVANT = "rejected_irrelevant"
DECISION_REJECTED_LOW_RELIABILITY = "rejected_low_reliability"
DECISION_REJECTED_INSUFFICIENT_EVIDENCE = "rejected_insufficient_evidence"
DECISION_NO_CANDIDATE = "no_candidate"
# Not one of the five states the trace is required to distinguish, but
# kept separate from NO_CANDIDATE so an internal failure is never
# mistaken for "nothing was selected".
DECISION_GATE_ERROR = "gate_error"

RELEVANCE_PASSED = "passed"
RELEVANCE_FAILED = "failed"
RELEVANCE_NOT_EVALUATED = "not_evaluated"
RELEVANCE_UNKNOWN = "unknown"

RELIABILITY_RELIABLE = "reliable"
RELIABILITY_UNRELIABLE = "unreliable"
RELIABILITY_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
RELIABILITY_NOT_EVALUATED = "not_evaluated"
RELIABILITY_UNKNOWN = "unknown"

# One reason code maps to exactly one decision state - the gate already
# distinguishes these cases via `reason`, so the trace only relabels it.
_REASON_TO_DECISION = {
    REASON_OK: DECISION_ACCEPTED,
    REASON_NOT_SELECTED: DECISION_NO_CANDIDATE,
    REASON_NOT_RELEVANT: DECISION_REJECTED_IRRELEVANT,
    REASON_NO_EVIDENCE: DECISION_REJECTED_INSUFFICIENT_EVIDENCE,
    REASON_INSUFFICIENT_RELIABILITY: DECISION_REJECTED_LOW_RELIABILITY,
    REASON_GATE_ERROR: DECISION_GATE_ERROR,
}

# Relevance is checked before reliability (see evaluate_learned_knowledge_gate
# below), so any reason reached after it - NO_EVIDENCE, INSUFFICIENT_RELIABILITY,
# OK - implies relevance passed; NOT_RELEVANT means it failed; NOT_SELECTED
# means it was never reached (no candidate to check).
_REASON_TO_RELEVANCE = {
    REASON_OK: RELEVANCE_PASSED,
    REASON_NOT_SELECTED: RELEVANCE_NOT_EVALUATED,
    REASON_NOT_RELEVANT: RELEVANCE_FAILED,
    REASON_NO_EVIDENCE: RELEVANCE_PASSED,
    REASON_INSUFFICIENT_RELIABILITY: RELEVANCE_PASSED,
    REASON_GATE_ERROR: RELEVANCE_UNKNOWN,
}

_REASON_TO_RELIABILITY = {
    REASON_OK: RELIABILITY_RELIABLE,
    REASON_NOT_SELECTED: RELIABILITY_NOT_EVALUATED,
    REASON_NOT_RELEVANT: RELIABILITY_NOT_EVALUATED,
    REASON_NO_EVIDENCE: RELIABILITY_INSUFFICIENT_EVIDENCE,
    REASON_INSUFFICIENT_RELIABILITY: RELIABILITY_UNRELIABLE,
    REASON_GATE_ERROR: RELIABILITY_UNKNOWN,
}


class LearnedKnowledgeGateTrace:
    """Read-only, structured decision trace for one already-computed
    `LearnedKnowledgeGateResult`. See the module docstring - this class
    only relabels fields the result already carries; it never re-derives
    them and cannot change the gate's outcome."""

    def __init__(self, result):
        reason = getattr(result, "reason", REASON_GATE_ERROR)
        self.decision = _REASON_TO_DECISION.get(reason, DECISION_GATE_ERROR)
        self.had_candidate = reason != REASON_NOT_SELECTED
        self.relevance_result = _REASON_TO_RELEVANCE.get(reason, RELEVANCE_UNKNOWN)
        self.reliability_result = _REASON_TO_RELIABILITY.get(reason, RELIABILITY_UNKNOWN)
        self.gate_status = getattr(result, "status", STATUS_REJECTED)
        self.supporting_records = getattr(result, "supporting_records", 0)
        self.average_confidence = getattr(result, "average_confidence", 0.0)
        self.success_rate = getattr(result, "success_rate", 0.0)
        self.min_confidence = getattr(result, "min_confidence", MIN_RELIABLE_CONFIDENCE)
        passed = self.gate_status == STATUS_PASSED
        self.rejection_reason = None if passed else reason
        self.detail = getattr(result, "detail", "")

    def __repr__(self):
        return f"LearnedKnowledgeGateTrace(decision={self.decision!r})"

    def to_dict(self):
        return {
            "decision": self.decision,
            "had_candidate": self.had_candidate,
            "relevance_result": self.relevance_result,
            "reliability_result": self.reliability_result,
            "gate_status": self.gate_status,
            "supporting_records": self.supporting_records,
            "average_confidence": self.average_confidence,
            "success_rate": self.success_rate,
            "min_confidence": self.min_confidence,
            "rejection_reason": self.rejection_reason,
            "detail": self.detail,
        }


def build_learned_knowledge_gate_trace(result):
    """The `LearnedKnowledgeGateTrace` for `result`, an already-computed
    `LearnedKnowledgeGateResult` from `evaluate_learned_knowledge_gate()`.
    Purely descriptive and read-only: it does not call the gate, the
    analyzer, or anything else, and building it never changes `result`
    or what was decided. Never raises - an unrecognized `result` simply
    yields a `DECISION_GATE_ERROR` trace."""
    try:
        return LearnedKnowledgeGateTrace(result)
    except Exception:  # noqa: BLE001 - a trace failure must never propagate
        return LearnedKnowledgeGateTrace(
            LearnedKnowledgeGateResult(STATUS_REJECTED, REASON_GATE_ERROR,
                                       "trace could not be built"))


def _normalize_name(text):
    return " ".join(str(text).lower().split())


def _is_relevant(selection, message):
    """Direct relevance, re-verified: the stored name is the matched
    term, and the term occurs as consecutive whole words in `message`."""
    record = selection.get("record") or {}
    name = record.get("name")
    term = selection.get("matched_term")
    if not isinstance(name, str) or not isinstance(term, str):
        return False
    if not name.strip() or _normalize_name(name) != _normalize_name(term):
        return False
    if not isinstance(message, str):
        return False
    words = [m.group().lower() for m in _WORD_RE.finditer(message)]
    term_words = [m.group().lower() for m in _WORD_RE.finditer(term)]
    if not term_words or len(term_words) > len(words):
        return False
    size = len(term_words)
    return any(words[i:i + size] == term_words for i in range(len(words) - size + 1))


def _evidence_records(record, relationships):
    """The entry's stored evidence as LearningRecords (module docstring)."""
    pattern = record["name"]
    default_source = record.get("source") or _DEFAULT_SOURCE

    def make(source, confidence):
        # None = "no confidence given" -> the KnowledgeSystem default (1.0)
        value = 1.0 if confidence is None else confidence
        return LearningRecord(source=source or default_source, pattern=pattern,
                              outcome=_OUTCOME_SUCCESS, confidence=value)

    records = []
    description = record.get("description")
    if isinstance(description, str) and description.strip():
        records.append(make(record.get("source"), record.get("confidence")))
    for direction in ("outgoing", "incoming"):
        for row in (relationships or {}).get(direction) or []:
            records.append(make(row.get("source_type"), row.get("confidence")))
    return records


def evaluate_learned_knowledge_gate(selection, message=None,
                                    min_confidence=MIN_RELIABLE_CONFIDENCE,
                                    min_records=MIN_SUPPORTING_RECORDS):
    """The `LearnedKnowledgeGateResult` for `selection` - a SELECTED
    `LearnedKnowledgeSelection` (language_intelligence/
    learned_knowledge_context.py), its `to_dict()` / `to_context()`, or
    anything else (which is simply not selected). `message` defaults to
    the selection's own `message`; pass the user's message to verify
    relevance against it explicitly. Never raises; mutates nothing."""
    try:
        data = selection.to_dict() if hasattr(selection, "to_dict") else selection
        if not isinstance(data, dict) or data.get("status") != "SELECTED":
            return LearnedKnowledgeGateResult(
                STATUS_REJECTED, REASON_NOT_SELECTED,
                "no directly relevant learned knowledge entry was selected",
                min_confidence=min_confidence)
        data = copy.deepcopy(data)
        record = data.get("record")
        if not isinstance(record, dict):
            return LearnedKnowledgeGateResult(
                STATUS_REJECTED, REASON_NOT_SELECTED, "the selection carries no record",
                min_confidence=min_confidence)

        text = data.get("message") if message is None else message
        if not _is_relevant(data, text):
            return LearnedKnowledgeGateResult(
                STATUS_REJECTED, REASON_NOT_RELEVANT,
                "the entry's name is not directly present in the message",
                min_confidence=min_confidence)

        records = _evidence_records(record, data.get("relationships"))
        analyzer = LearningAnalyzer()
        pattern = record["name"]
        report = analyzer.get_pattern_report(records, pattern)
        numbers = dict(supporting_records=report["total_records"],
                       average_confidence=report["average_confidence"],
                       success_rate=report["success_rate"], min_confidence=min_confidence)
        if report["total_records"] < min_records:
            return LearnedKnowledgeGateResult(
                STATUS_REJECTED, REASON_NO_EVIDENCE,
                "the entry has no valid stored evidence to rely on", **numbers)
        if not analyzer.is_pattern_reliable(
                records, pattern, min_confidence=min_confidence, min_records=min_records):
            return LearnedKnowledgeGateResult(
                STATUS_REJECTED, REASON_INSUFFICIENT_RELIABILITY,
                "the entry's stored confidence is below the reliability threshold", **numbers)
        return LearnedKnowledgeGateResult(
            STATUS_PASSED, REASON_OK, "directly relevant and sufficiently reliable", **numbers)
    except Exception as exc:  # noqa: BLE001 - the gate never breaks the conversation path
        return LearnedKnowledgeGateResult(
            STATUS_REJECTED, REASON_GATE_ERROR, f"gate could not be evaluated: {exc}",
            min_confidence=min_confidence)
