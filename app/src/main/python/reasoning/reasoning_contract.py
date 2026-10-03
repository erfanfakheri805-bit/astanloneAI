"""
Reasoning Contract (Prompt 680)
=================================
A small, read-only, structured view of a `ReasoningResult` for the planning layer:

    ReasoningResult (unchanged) -> build_reasoning_outcome() -> ReasoningOutcome

It exists so planning can consume status, answer/conclusion, relevant CURRENT knowledge, uncertainty,
ambiguity, assumptions, evidence and a next-action recommendation from ONE JSON-shaped record without
re-deriving anything. It does NOT change `ReasoningEngine.reason()` / `ReasoningResult` in any way
(Section 3 contracts, e.g. "a case-ambiguous name answers `unknown`", are preserved exactly).

Ambiguity recovery: the engine reports a case-ambiguous knowledge name as `unknown` ("not in the knowledge
base"). That is a locked Section 3 contract, so it is left alone; this module recovers the distinction
read-only via `KnowledgeSystem.resolve_current_name()` and reports it as `ambiguity`/`effective_status`
while `status` keeps the engine's own value. Inactive records are never current knowledge: they are named
only as "inactive" (no description, no relationship), and ambiguous candidates are listed by name only -
nothing is ever chosen among them. Never writes to knowledge, memory or context.
"""

from reasoning.query_parsing import parse_query
from reasoning.reasoning_result import (
    STATUS_ANSWERED, STATUS_UNKNOWN, STATUS_AMBIGUOUS, STATUS_CONTRADICTION, STATUS_LIMIT_REACHED,
)

# Next-action recommendations (small fixed vocabulary, deterministic).
ACTION_ANSWER = "answer"
ACTION_CLARIFY = "clarify"
ACTION_GATHER_INFORMATION = "gather_information"
ACTION_RESOLVE_CONTRADICTION = "resolve_contradiction"
ACTION_NARROW_QUESTION = "narrow_question"

_ACTION_BY_STATUS = {
    STATUS_ANSWERED: ACTION_ANSWER,
    STATUS_UNKNOWN: ACTION_GATHER_INFORMATION,
    STATUS_AMBIGUOUS: ACTION_CLARIFY,
    STATUS_CONTRADICTION: ACTION_RESOLVE_CONTRADICTION,
    STATUS_LIMIT_REACHED: ACTION_NARROW_QUESTION,
}


def classify_current_terms(knowledge, terms):
    """Read-only classification of `terms` against CURRENT knowledge (Prompt 667 resolution).

    Returns {"current": [record summaries], "ambiguous": [{"term", "candidates"}], "inactive": [term],
    "unknown": [term]} - each term lands in exactly one bucket, in first-seen order, duplicates ignored.
    Records carry name/description/kind/status only. Without a knowledge object every list is empty."""
    out = {"current": [], "ambiguous": [], "inactive": [], "unknown": []}
    resolve = getattr(knowledge, "resolve_current_name", None)
    if not callable(resolve):
        return out
    seen_terms, seen_names = set(), set()
    for term in terms or []:
        if not isinstance(term, str) or not term.strip() or term in seen_terms:
            continue
        seen_terms.add(term)
        res = resolve(term)
        status = res.get("status")
        if status in ("exact", "case_insensitive") and res.get("record"):
            rec = res["record"]
            if rec["name"] not in seen_names:
                seen_names.add(rec["name"])
                out["current"].append({
                    "name": rec["name"], "description": rec.get("description"),
                    "kind": rec.get("kind"), "status": rec.get("status"), "matched_by": status,
                    "term": term,
                })
        elif status == "ambiguous":
            out["ambiguous"].append({"term": term, "candidates": list(res.get("candidates") or [])})
        elif status == "inactive":
            out["inactive"].append(term)
        else:
            out["unknown"].append(term)
    return out


class ReasoningOutcome:
    """Plain, JSON-shaped record; see module docstring. `status` is the engine's own status unchanged;
    `effective_status` additionally reflects ambiguity recovered from current-knowledge resolution."""

    __slots__ = (
        "query", "status", "effective_status", "answer", "conclusion", "relevant_knowledge",
        "uncertainty", "ambiguity", "assumptions", "evidence", "next_action",
    )

    def __init__(self, query):
        self.query = query
        self.status = STATUS_UNKNOWN
        self.effective_status = STATUS_UNKNOWN
        self.answer = None
        self.conclusion = None
        self.relevant_knowledge = []
        self.uncertainty = {}
        self.ambiguity = {"reference_ambiguous": False, "ambiguous_terms": []}
        self.assumptions = []
        self.evidence = {}
        self.next_action = ACTION_GATHER_INFORMATION

    @property
    def is_ambiguous(self):
        return bool(self.ambiguity["reference_ambiguous"] or self.ambiguity["ambiguous_terms"])

    def to_dict(self):
        return {
            "query": self.query,
            "status": self.status,
            "effective_status": self.effective_status,
            "answer": self.answer,
            "conclusion": None if self.conclusion is None else dict(self.conclusion),
            "relevant_knowledge": [dict(k) for k in self.relevant_knowledge],
            "uncertainty": {k: (list(v) if isinstance(v, list) else v) for k, v in self.uncertainty.items()},
            "ambiguity": {
                "reference_ambiguous": self.ambiguity["reference_ambiguous"],
                "ambiguous_terms": [dict(t, candidates=list(t["candidates"]))
                                    for t in self.ambiguity["ambiguous_terms"]],
            },
            "assumptions": list(self.assumptions),
            "evidence": {k: (list(v) if isinstance(v, list) else v) for k, v in self.evidence.items()},
            "next_action": self.next_action,
        }


def build_reasoning_outcome(result, knowledge=None, terms=None):
    """Build a ReasoningOutcome from an existing ReasoningResult (never mutated). `terms` (optional) are
    extra terms to classify against current knowledge; the query's own parsed subject/object are always
    included. Never raises for a well-formed ReasoningResult."""
    out = ReasoningOutcome(getattr(result, "query", None))
    out.status = result.status
    out.answer = result.answer
    out.conclusion = None if result.conclusion is None else dict(result.conclusion)

    check = []
    try:
        parsed = parse_query(result.query, request_forms=True)
        check.extend(t for t in (parsed.subject, getattr(parsed, "object", None)) if t)
    except Exception:  # noqa: BLE001 - parsing failure just means fewer terms
        pass
    check.extend(terms or [])
    classes = classify_current_terms(knowledge, check)

    known = []
    for fact in result.supporting_facts:
        known.append({"name": fact.get("name"), "description": fact.get("description"),
                      "kind": fact.get("kind"), "status": fact.get("status")})
    names = {k["name"] for k in known}
    for rec in classes["current"]:
        if rec["name"] not in names:
            names.add(rec["name"])
            known.append({"name": rec["name"], "description": rec["description"],
                          "kind": rec["kind"], "status": rec["status"]})
    out.relevant_knowledge = known

    out.ambiguity = {
        "reference_ambiguous": result.status == STATUS_AMBIGUOUS,
        "ambiguous_terms": [dict(t) for t in classes["ambiguous"]],
    }
    out.effective_status = STATUS_AMBIGUOUS if out.is_ambiguous else result.status

    out.uncertainty = {
        "confidence": round(result.confidence, 4),
        "unknowns": list(result.unknowns),
        "contradictions": len(result.contradictions),
        "limit_reached": result.status == STATUS_LIMIT_REACHED,
        "inactive_terms": list(classes["inactive"]),
        "unknown_terms": list(classes["unknown"]),
    }

    for step in result.reasoning_steps:
        details = step.get("details") or {}
        if step.get("description") == "context resolution" and details.get("resolved") \
                and not details.get("ambiguous"):
            out.assumptions.append(
                f"'{details.get('reference')}' was resolved to '{details.get('resolved')}' from recent context")
    for rec in classes["current"]:
        if rec["matched_by"] == "case_insensitive":
            out.assumptions.append(
                f"'{rec['term']}' was matched to the stored name '{rec['name']}' ignoring case")
    if result.rules_used:
        out.assumptions.append("inference rules applied: " + ", ".join(result.rules_used))

    out.evidence = {
        "supporting_facts": len(result.supporting_facts),
        "supporting_relationships": len(result.supporting_relationships),
        "rules_used": list(result.rules_used),
        "reasoning_steps": len(result.reasoning_steps),
        "warnings": list(result.warnings),
    }

    out.next_action = (ACTION_CLARIFY if out.is_ambiguous
                       else _ACTION_BY_STATUS.get(result.status, ACTION_GATHER_INFORMATION))
    return out
