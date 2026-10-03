"""
Request Context (Prompt 680)
==============================
A minimal, per-request, IN-MEMORY working record for the Section 4 flow:

    Request Context -> Reasoning Result -> Goal/Information Gaps -> Plan -> Plan Validation
        -> Inert Execution Handoff (planning/execution_handoff.py)

It is NOT persistent memory and NOT a second source of truth: it is built fresh for one request, holds a
snapshot of what existing components reported (current KnowledgeSystem state via the Prompt 667 read
boundary, the existing capability registries, the existing ReasoningEngine), and is discarded with the
request. Building one writes nothing (no knowledge, memory, conversation context, goal or plan). Inactive
knowledge is never current; ambiguous knowledge is reported as a blocking gap and never resolved by
picking a candidate; historical learning events are never read.
"""

from planning.goal_detection import is_goal_oriented
from reasoning.query_parsing import parse_query
from reasoning.reasoning_contract import build_reasoning_outcome, classify_current_terms
from understanding.normalization import normalize
from understanding.term_extraction import extract_candidate_terms

INTENT_GOAL_REQUEST = "goal_request"
MAX_OBSERVATIONS = 50

# Information-gap codes.
GAP_EMPTY_REQUEST = "EMPTY_REQUEST"
GAP_AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
GAP_AMBIGUOUS_KNOWLEDGE_TERM = "AMBIGUOUS_KNOWLEDGE_TERM"
GAP_CONTRADICTORY_KNOWLEDGE = "CONTRADICTORY_KNOWLEDGE"
GAP_UNKNOWN_INFORMATION = "UNKNOWN_INFORMATION"
GAP_INACTIVE_KNOWLEDGE_TERM = "INACTIVE_KNOWLEDGE_TERM"
GAP_REASONING_LIMIT = "REASONING_LIMIT"


class RequestContext:
    __slots__ = (
        "original_input", "normalized_request", "intent", "terms", "knowledge_context", "capabilities",
        "reasoning", "goal", "constraints", "information_gaps", "proposed_plan", "validation",
        "execution_eligible", "observations", "persistent",
    )

    def __init__(self, original_input):
        self.original_input = original_input
        self.normalized_request = ""
        self.intent = None
        self.terms = []
        self.knowledge_context = {"current": [], "ambiguous": [], "inactive": [], "unknown": []}
        self.capabilities = {"registered": [], "executable": []}
        self.reasoning = None            # ReasoningOutcome
        self.goal = None
        self.constraints = []
        self.information_gaps = []
        self.proposed_plan = None        # an existing planning.plan.Plan
        self.validation = None           # PlanValidationResult
        self.execution_eligible = False
        self.observations = []
        self.persistent = False          # always False: this record is never stored

    def add_gap(self, code, message, blocking, **details):
        gap = {"code": code, "message": message, "blocking": bool(blocking)}
        gap.update(details)
        self.information_gaps.append(gap)
        return gap

    def blocking_gaps(self):
        return [g for g in self.information_gaps if g["blocking"]]

    def add_observation(self, kind, detail=None):
        """Bounded working notes/results for this request only (oldest dropped past MAX_OBSERVATIONS)."""
        self.observations.append({"kind": kind, "detail": detail})
        del self.observations[:-MAX_OBSERVATIONS]

    def attach_plan(self, plan):
        self.proposed_plan = plan
        self.validation = None
        self.execution_eligible = False

    def attach_validation(self, validation):
        """Record the plan validation. Execution eligibility needs a valid, eligible plan AND no blocking
        information gap - it can never be True otherwise."""
        self.validation = validation
        self.execution_eligible = bool(
            validation is not None and validation.valid and validation.execution_eligible
            and not self.blocking_gaps()
        )

    def to_dict(self):
        return {
            "original_input": self.original_input,
            "normalized_request": self.normalized_request,
            "intent": self.intent,
            "terms": list(self.terms),
            "knowledge_context": {
                "current": [dict(r) for r in self.knowledge_context["current"]],
                "ambiguous": [dict(a, candidates=list(a["candidates"]))
                              for a in self.knowledge_context["ambiguous"]],
                "inactive": list(self.knowledge_context["inactive"]),
                "unknown": list(self.knowledge_context["unknown"]),
            },
            "capabilities": {
                "registered": [dict(c) for c in self.capabilities["registered"]],
                "executable": [dict(c) for c in self.capabilities["executable"]],
            },
            "reasoning": None if self.reasoning is None else self.reasoning.to_dict(),
            "goal": self.goal,
            "constraints": list(self.constraints),
            "information_gaps": [dict(g) for g in self.information_gaps],
            "proposed_plan": None if self.proposed_plan is None else self.proposed_plan.to_dict(),
            "validation": None if self.validation is None else self.validation.to_dict(),
            "execution_eligible": self.execution_eligible,
            "observations": [dict(o) for o in self.observations],
            "persistent": self.persistent,
        }


def _capability_snapshot(capability_system, executable_registry):
    snap = {"registered": [], "executable": []}
    if capability_system is not None:
        snap["registered"] = [
            {"name": r["name"], "enabled": bool(r["enabled"]), "status": r["status"]}
            for r in capability_system.all()
        ]
    if executable_registry is not None:
        snap["executable"] = [dict(e) for e in executable_registry.list_all()]
    return snap


def build_request_context(raw_text, knowledge, reasoning_engine, capability_system=None,
                          executable_registry=None, conversation_context=None):
    """Prepare a RequestContext for `raw_text` (read-only; see module docstring). Deterministic."""
    ctx = RequestContext(raw_text)
    ctx.normalized_request = normalize(raw_text).normalized_text
    ctx.capabilities = _capability_snapshot(capability_system, executable_registry)
    if not ctx.normalized_request:
        ctx.intent = "empty"
        ctx.add_gap(GAP_EMPTY_REQUEST, "The request is empty.", True)
        return ctx

    goal_request = is_goal_oriented(ctx.normalized_request)
    ctx.intent = INTENT_GOAL_REQUEST if goal_request else parse_query(
        ctx.normalized_request, request_forms=True).intent
    if goal_request:
        ctx.goal = ctx.normalized_request
    ctx.terms = extract_candidate_terms(ctx.normalized_request)
    ctx.knowledge_context = classify_current_terms(knowledge, ctx.terms)

    result = reasoning_engine.reason(ctx.normalized_request, context=conversation_context,
                                     request_forms=True)
    ctx.reasoning = build_reasoning_outcome(result, knowledge, terms=ctx.terms)
    # Terms named by the reasoning subject may not be in ctx.terms; merge any extra ambiguity found.
    known_terms = {a["term"] for a in ctx.knowledge_context["ambiguous"]}
    for amb in ctx.reasoning.ambiguity["ambiguous_terms"]:
        if amb["term"] not in known_terms:
            ctx.knowledge_context["ambiguous"].append(dict(amb))

    status = ctx.reasoning.status
    if status == "ambiguous":
        ctx.add_gap(GAP_AMBIGUOUS_REFERENCE, "A reference in the request could not be resolved.", True)
    elif status == "contradiction":
        ctx.add_gap(GAP_CONTRADICTORY_KNOWLEDGE, "Stored knowledge about this is contradictory.", True)
    elif status == "limit_reached":
        ctx.add_gap(GAP_REASONING_LIMIT, "Reasoning stopped at its configured limit.", False)
    elif status == "unknown" and not goal_request and not ctx.knowledge_context["ambiguous"]:
        ctx.add_gap(GAP_UNKNOWN_INFORMATION, "Not enough current knowledge to answer.", False)
    for amb in ctx.knowledge_context["ambiguous"]:
        ctx.add_gap(GAP_AMBIGUOUS_KNOWLEDGE_TERM,
                    f"'{amb['term']}' matches several current knowledge records.", True,
                    term=amb["term"], candidates=list(amb["candidates"]))
    for term in ctx.knowledge_context["inactive"]:
        ctx.add_gap(GAP_INACTIVE_KNOWLEDGE_TERM,
                    f"'{term}' is only known as inactive knowledge, which is not current.", False, term=term)
    return ctx
