"""
Reasoning Result
=================
The structured object returned by ReasoningEngine.reason() - the
"REASONING RESULT" box at the end of this stage's pipeline:

    USER INPUT -> UNDERSTANDING -> CONTEXT -> KNOWLEDGE RETRIEVAL
        -> REASONING ENGINE -> REASONING RESULT

Same convention already used by UnderstandingResult
(understanding/result.py) and LearningResult (learning/learning_result.py):
a plain, JSON-shaped record rather than formatted text, so a caller (a
UI, a test, AEL's ASK handler, a future planning/skills stage) gets
everything it needs without re-querying storage or re-deriving anything
from a message string.

Nothing here pretends to more certainty than the engine actually has -
`status` is always one of the STATUS_* constants below, `confidence` is
always a deterministic float in [0.0, 1.0] (see reasoning_engine.py /
rules.py for how it's computed - never random, never a bare guess), and
`answer` is None whenever `status` is not STATUS_ANSWERED. See
reasoning_engine.py module docstring for the "no fake intelligence"
rule this object exists to make checkable from the outside.
"""

# Every reason() call ends in exactly one of these. Kept as a small
# fixed vocabulary (not a free-form string) so callers can branch on it
# reliably.
STATUS_ANSWERED = "answered"            # a direct or inferred conclusion was produced
STATUS_UNKNOWN = "unknown"              # not enough stored knowledge to answer - no guess made
STATUS_AMBIGUOUS = "ambiguous"          # a context reference ("it", "this") could not be resolved
STATUS_CONTRADICTION = "contradiction"  # the knowledge needed to answer is internally inconsistent
STATUS_LIMIT_REACHED = "limit_reached"  # a configured reasoning limit stopped the search early

ALL_STATUSES = (
    STATUS_ANSWERED, STATUS_UNKNOWN, STATUS_AMBIGUOUS, STATUS_CONTRADICTION, STATUS_LIMIT_REACHED,
)


class ReasoningResult:
    """`reasoning_steps` is the machine-readable trace (item 14 of the
    stage spec): an ordered list of small dicts, one per step actually
    taken, built with `add_step()` as reasoning proceeds - never
    reconstructed after the fact. `supporting_facts` holds direct
    knowledge-table rows consulted; `supporting_relationships` holds
    relationship-table rows consulted (direct hops and/or rule
    premises); `rules_used` holds the *names* of any rules that fired
    (see reasoning/rules.py) - empty for a purely direct-lookup or
    plain-traversal answer, since not every conclusion involves a
    rule."""

    def __init__(self, query):
        self.query = query
        self.answer = None                   # short human-readable answer text, or None
        self.conclusion = None               # structured {"subject","relation","object"} or None
        self.reasoning_steps = []            # machine-readable trace - see add_step()
        self.supporting_facts = []           # list of knowledge-table rows (dicts)
        self.supporting_relationships = []   # list of relationship-table rows (dicts)
        self.rules_used = []                 # list of rule names that fired
        self.confidence = 0.0                # deterministic, in [0.0, 1.0]
        self.contradictions = []             # list of {"a": row, "b": row} conflicting pairs
        self.unknowns = []                   # human-readable notes on what wasn't known
        self.status = STATUS_UNKNOWN
        self.warnings = []

    # ------------------------------------------------------------------
    # Trace building - the ONLY way reasoning_steps is populated, so the
    # trace always matches the actual sequence of work performed.
    # ------------------------------------------------------------------
    def add_step(self, description, **details):
        step = {"step": len(self.reasoning_steps) + 1, "description": description}
        if details:
            step["details"] = details
        self.reasoning_steps.append(step)
        return step

    # ------------------------------------------------------------------
    # Presentation helper - deliberately hides trace/rule-name/internal
    # plumbing from a normal user-facing reply (spec item 2: "do not
    # expose unnecessary internal implementation details to normal
    # users"). Callers that DO want the internals (a dev panel, a test,
    # future self-diagnostics) should read the structured fields above
    # or call to_dict() directly instead of parsing this string.
    # ------------------------------------------------------------------
    def to_summary_text(self):
        if self.status == STATUS_ANSWERED:
            return self.answer or "Answered, but no summary text was set."
        if self.status == STATUS_AMBIGUOUS:
            return "That reference is ambiguous - could you say what you mean specifically?"
        if self.status == STATUS_CONTRADICTION:
            return "I have conflicting information about that and can't give a confident answer."
        if self.status == STATUS_LIMIT_REACHED:
            return "I'd need to reason further than my configured limits allow to answer that."
        # STATUS_UNKNOWN
        if self.unknowns:
            return self.unknowns[0]
        return "I don't have enough information to answer that yet."

    def __repr__(self):
        return (
            f"ReasoningResult(query={self.query!r}, status={self.status!r}, "
            f"confidence={self.confidence:.2f}, steps={len(self.reasoning_steps)}, "
            f"rules_used={self.rules_used})"
        )

    def to_dict(self):
        return {
            "query": self.query,
            "answer": self.answer,
            "conclusion": self.conclusion,
            "reasoning_steps": self.reasoning_steps,
            "supporting_facts": self.supporting_facts,
            "supporting_relationships": self.supporting_relationships,
            "rules_used": self.rules_used,
            "confidence": round(self.confidence, 4),
            "contradictions": self.contradictions,
            "unknowns": self.unknowns,
            "status": self.status,
            "warnings": self.warnings,
        }
