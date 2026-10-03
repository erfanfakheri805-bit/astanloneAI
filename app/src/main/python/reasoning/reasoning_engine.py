"""
Reasoning Engine
=================
A deliberately small, deterministic reasoning layer over the Knowledge
Graph.

This is NOT a general inference engine and does not pretend to be one.
It only reasons over relationships and relation types the application
already has explicit, structured records for - it never guesses or
fabricates a conclusion. Where there isn't enough stored information,
this module says so (STATUS_UNKNOWN) rather than inventing an answer.
See module docstring of reasoning/reasoning_result.py for the
STATUS_* vocabulary every reason() call ends in.

It owns no storage itself; it composes the Knowledge System, the same
way ConceptSystem does, keeping responsibilities clean.

Stage 5 pipeline
------------------
This stage adds a real reasoning pipeline on top of the direct-lookup/
traversal/contradiction primitives that already existed (and are kept,
byte-for-byte-compatible in behaviour, below - core.py, ael/interpreter.py
and learning/learning_system.py all call them directly):

    USER INPUT (query text)
      -> QUERY PARSING              (query_parsing.py)
      -> CONTEXT RESOLUTION         (context/reference_resolution.py, optional)
      -> KNOWLEDGE RETRIEVAL        (direct lookup / relationships_for)
      -> REASONING
           - DIRECT LOOKUP
           - RELATION TRAVERSAL     (transitive-relation closure)
           - RULE EVALUATION        (rules.py)
           - MULTI-HOP INFERENCE    (rule chains / transitive closure)
           - CONTRADICTION CHECK
           - CONFIDENCE EVALUATION
      -> REASONING RESULT           (reasoning_result.py)

Two distinct inference mechanisms feed "RULE EVALUATION" /
"MULTI-HOP INFERENCE" above - see rules.py's module docstring for why
they are kept separate:

    1. Transitive-relation closure (rules.TRANSITIVE_RELATION_TYPES) -
       a cycle-safe, depth-bounded graph walk along edges of a SINGLE
       relation type, reusing the same walking logic as traverse().
    2. The Rule engine (rules.RuleEngine) - fixed-length premise chains
       across DIFFERENT relation types (e.g. IS_A + USED_FOR -> USED_FOR).

Neither mechanism ever writes an inferred conclusion back into the
Knowledge System - see the stage spec's "do not automatically convert
every inferred conclusion into permanent knowledge" requirement. An
inferred fact lives only inside the ReasoningResult returned to the
caller, clearly distinguished (via `rules_used`/reasoning_steps and the
"inferred" vs "direct" language in `answer`) from a fact that came from
a direct lookup.

Stage 6 addition
------------------
The RULE EVALUATION step above can now be backed by a persistent,
validated reasoning/rule_registry.py `RuleRegistry` instead of (or as
well as) an in-memory rules.RuleEngine - pass it as `rule_registry=` to
__init__. This is a pure swap of *where the rule set comes from*;
`_try_rule`/`_infer` below are completely unchanged and have no idea
whether `self.rules` is backed by storage or not. See
ReasoningEngine.__init__ and reasoning/rule_registry.py's module
docstring for how the two are wired together.

Reasoning limits
------------------
Every search below is bounded by a `Budget` (max reasoning steps,
facts inspected, and rules evaluated - see DEFAULT_MAX_* below) so a
malformed or cyclic graph can never cause runaway work; traversal is
additionally cycle-safe via a `visited` set, the same technique
already used by `traverse()`/`find_path()`.
"""

from datetime import datetime, timezone

from .query_parsing import (
    parse_query, INTENT_WHAT_IS, INTENT_RELATION_QUERY, INTENT_VERIFY_RELATION, INTENT_VERIFY_IS_A,
)
from .reasoning_result import (
    ReasoningResult, STATUS_ANSWERED, STATUS_UNKNOWN, STATUS_AMBIGUOUS, STATUS_CONTRADICTION,
    STATUS_LIMIT_REACHED,
)
from .rules import RuleEngine, TRANSITIVE_RELATION_TYPES, DEFAULT_FACT_CONFIDENCE, DEPTH_DECAY
from .relation_phrasing import phrase as phrase_relation

# Reasoning limits (item 15 of the stage spec) - deliberately small,
# mobile-friendly defaults. Every reason() call can override these
# explicitly; nothing here is a hidden global.
DEFAULT_MAX_INFERENCE_DEPTH = 4
DEFAULT_MAX_RULES_EVALUATED = 25
DEFAULT_MAX_FACTS_INSPECTED = 200

# Words that name a reference rather than a concept - the same simple,
# closed vocabulary context/reference_resolution.py itself classifies
# as a reference. Used here only to decide *whether* to even attempt
# context resolution when no context was supplied (see reason() below);
# the actual resolution logic is never duplicated here.
_REFERENCE_WORDS = {"it", "this", "that", "they", "them", "these", "those"}


class Budget:
    """Mutable counters shared across one reason() call, so every
    sub-search (rule evaluation, transitive closure) draws from the
    same pool instead of each getting its own separate allowance -
    that is what actually prevents a query with many candidate rules
    from doing unbounded total work even though each individual rule
    is itself bounded."""

    def __init__(self, max_depth, max_rules, max_facts):
        self.max_depth = max_depth
        self.max_rules = max_rules
        self.max_facts = max_facts
        self.rules_evaluated = 0
        self.facts_inspected = 0
        self.limit_hit = False

    def take_fact(self):
        self.facts_inspected += 1
        if self.facts_inspected > self.max_facts:
            self.limit_hit = True
            return False
        return True

    def take_rule(self):
        if self.rules_evaluated >= self.max_rules:
            self.limit_hit = True
            return False
        self.rules_evaluated += 1
        return True


class InferredFact:
    """One derived (not directly stored) relationship, with enough
    metadata to keep it clearly distinguishable from a direct fact -
    item 8 of the stage spec ("every inferred conclusion should be
    distinguishable from directly learned knowledge")."""

    def __init__(self, from_name, relation_type, to_name, confidence, depth,
                 supporting_relationships, rule_name=None, rule_id=None, bindings=None):
        self.from_name = from_name
        self.relation_type = relation_type
        self.to_name = to_name
        self.confidence = confidence
        self.depth = depth
        self.supporting_relationships = supporting_relationships
        self.rule_name = rule_name  # None for transitive-closure inferences (no Rule object involved)
        self.rule_id = rule_id      # None for the same reason - see rule_name above
        self.bindings = bindings or {}  # variable -> bound entity name, for explanation (item 10/20)

    def provenance(self):
        """Structured record of how this conclusion was derived - item 10
        ("every rule-derived conclusion should record: rule ID, supporting
        facts, variable bindings, inference depth, confidence, timestamp").
        Built entirely from data already produced during actual matching
        (never reconstructed/guessed after the fact - item 20)."""
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "bindings": dict(self.bindings),
            "supporting_facts": list(self.supporting_relationships),
            "depth": self.depth,
            "confidence": self.confidence,
            "timestamp": _now(),
        }


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fact_confidence(rel):
    return rel["confidence"] if rel.get("confidence") is not None else DEFAULT_FACT_CONFIDENCE


def _depth_confidence(evidence_confidences, depth, weight=1.0):
    """Deterministic confidence for a derived conclusion: the weakest
    piece of evidence it depends on (item 9: "account for the weakest
    important evidence"), discounted per additional hop, times the
    rule's own fixed weight if any. Never random; never a bare average
    that would let many weak facts add up to a falsely strong one."""
    base = min(evidence_confidences) if evidence_confidences else DEFAULT_FACT_CONFIDENCE
    decayed = base * (DEPTH_DECAY ** max(0, depth - 1)) * weight
    return max(0.0, min(1.0, decayed))


class ReasoningEngine:
    # Relation-type pairs that directly contradict each other when they
    # hold between the exact same ordered pair of names (e.g. "Python
    # IS_A language" and "Python IS_NOT_A language" cannot both be true).
    # This is intentionally small and easy to extend - it is a starting
    # point, not a complete ontology of opposites. Relation types with no
    # entry here (e.g. USES, PART_OF) simply aren't checked for
    # contradiction yet; that is an honest gap, not a silent one, since
    # `check_new_relationship` returns None (no contradiction found)
    # rather than claiming to have verified consistency.
    OPPOSITE_RELATIONS = {
        "IS_A": "IS_NOT_A",
        "IS_NOT_A": "IS_A",
        "SIMILAR_TO": "DIFFERENT_FROM",
        "DIFFERENT_FROM": "SIMILAR_TO",
    }

    def __init__(self, knowledge_system, rule_engine=None, rule_registry=None):
        self.knowledge = knowledge_system
        # Three ways to supply the rule set this engine evaluates against,
        # in priority order:
        #   1. `rule_registry` (reasoning/rule_registry.py's RuleRegistry) -
        #      Stage 6's persistent, validated, enable/disable-aware store.
        #      We evaluate `rule_registry.engine` directly (a plain
        #      RuleEngine kept in sync with storage - see
        #      RuleRegistry.reload()), so nothing below this line needs to
        #      change to "use the Rule Registry" (item 19).
        #   2. `rule_engine` - a caller-supplied RuleEngine, unchanged from
        #      before this stage (still used directly by
        #      tests/test_reasoning_engine.py).
        #   3. The small starter set in rules.default_rules(), unchanged.
        # `self.rule_registry` is kept (possibly None) purely so a caller
        # can look up full rule metadata/provenance for explanation (item
        # 20) without this class needing to know about persistence itself.
        self.rule_registry = rule_registry
        if rule_registry is not None:
            self.rules = rule_registry.engine
        else:
            self.rules = rule_engine if rule_engine is not None else RuleEngine()

    # ==================================================================
    # Pre-existing primitives (unchanged behaviour - relied on by
    # core.py, ael/interpreter.py, learning/learning_system.py)
    # ==================================================================

    def _current_rels(self, name):
        """Prompt 668: the ONLY relationship read used for current reasoning/inference.

        Rows with an explicitly inactive endpoint (Prompt 663 lifecycle) are dropped at this
        read boundary, so no IS_A / traversal / rule / contradiction / summary fact is derived
        from inactive knowledge and no multi-hop chain passes through it. Stored rows and the raw
        KnowledgeSystem.relationships_for() are untouched; reactivation is effective immediately
        (nothing is cached). Falls back to the raw read for a knowledge object without
        current_relationships_for (test doubles)."""
        fn = getattr(self.knowledge, "current_relationships_for", None)
        return fn(name) if callable(fn) else self.knowledge.relationships_for(name)

    # ------------------------------------------------------------------
    # Direct fact lookup
    # ------------------------------------------------------------------
    def lookup(self, name):
        return self.knowledge.get(name)

    # ------------------------------------------------------------------
    # Relationship traversal (multi-hop reasoning)
    # ------------------------------------------------------------------
    def traverse(self, name, max_hops=2):
        """Breadth-first traversal over OUTGOING relationships starting at
        `name`, up to `max_hops` edges away. Returns a list of hop dicts:
        [{"hop": 1, "from": ..., "relation": ..., "to": ...}, ...].
        Cycle-safe: each node is expanded at most once, so a loop in the
        graph (A DEPENDS_ON B, B DEPENDS_ON A) cannot cause infinite work.
        """
        if max_hops < 1:
            return []

        visited = {name}
        frontier = [name]
        hops = []

        for hop in range(1, max_hops + 1):
            next_frontier = []
            for node in frontier:
                outgoing = self._current_rels(node)["outgoing"]
                for rel in outgoing:
                    hops.append({
                        "hop": hop,
                        "from": node,
                        "relation": rel["relation_type"],
                        "to": rel["to_name"],
                    })
                    if rel["to_name"] not in visited:
                        visited.add(rel["to_name"])
                        next_frontier.append(rel["to_name"])
            frontier = next_frontier
            if not frontier:
                break

        return hops

    def find_path(self, start, end, max_hops=4):
        """Breadth-first search for the shortest chain of outgoing
        relationships connecting `start` to `end`. Returns a list of hop
        dicts forming the path (empty list if start == end), or None if
        no path exists within `max_hops`. This is the substrate for
        dependency-style reasoning (e.g. "does A eventually DEPEND_ON B?")
        without fabricating a connection that isn't actually recorded.
        """
        if start == end:
            return []

        visited = {start}
        queue = [(start, [])]

        for _ in range(max_hops):
            next_queue = []
            for node, path in queue:
                outgoing = self._current_rels(node)["outgoing"]
                for rel in outgoing:
                    step = {"from": node, "relation": rel["relation_type"], "to": rel["to_name"]}
                    new_path = path + [step]
                    if rel["to_name"] == end:
                        return new_path
                    if rel["to_name"] not in visited:
                        visited.add(rel["to_name"])
                        next_queue.append((rel["to_name"], new_path))
            queue = next_queue
            if not queue:
                break

        return None

    # ------------------------------------------------------------------
    # Contradiction detection (narrow, explicit - see OPPOSITE_RELATIONS)
    # ------------------------------------------------------------------
    def check_new_relationship(self, from_name, relation_type, to_name):
        """Check whether storing (from_name, relation_type, to_name) would
        directly contradict a relationship already recorded between the
        SAME pair of names. Returns the conflicting relationship row if
        so, otherwise None. Deliberately narrow: it only catches the case
        where the exact opposite relation already holds between the same
        two names - it is not a general-purpose consistency checker."""
        opposite = self.OPPOSITE_RELATIONS.get(relation_type)
        if not opposite:
            return None
        existing = self._current_rels(from_name)["outgoing"]
        for rel in existing:
            if rel["to_name"] == to_name and rel["relation_type"] == opposite:
                return rel
        return None

    def contradictions_for(self, name):
        """Scan `name`'s outgoing relationships for any pair that directly
        contradicts another (same target, opposite relation type), using
        the same narrow definition as `check_new_relationship`. Returns a
        list of (relation_a, relation_b) row pairs."""
        outgoing = self._current_rels(name)["outgoing"]
        found = []
        seen_pairs = set()
        for rel in outgoing:
            opposite = self.OPPOSITE_RELATIONS.get(rel["relation_type"])
            if not opposite:
                continue
            for other in outgoing:
                if other is rel:
                    continue
                if other["to_name"] == rel["to_name"] and other["relation_type"] == opposite:
                    pair_key = tuple(sorted((rel["id"], other["id"])))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        found.append((rel, other))
        return found

    # ------------------------------------------------------------------
    # Consistency checking (item 11) - a bounded, honest scan, not a
    # claim of complete logical consistency. Reuses contradictions_for
    # per name; with no name given, scans up to `max_entities` known
    # names so a large knowledge base can't turn an idle health-check
    # into unbounded work.
    # ------------------------------------------------------------------
    def check_consistency(self, name=None, max_entities=200):
        """Returns {"checked": [names], "contradictions": [(rel_a, rel_b), ...],
        "consistent": bool}. "consistent" only claims no *detected*
        contradiction among the narrow OPPOSITE_RELATIONS pairs checked -
        see contradictions_for's own docstring for what this does not
        catch (spec item 11: "do not attempt perfect logical
        consistency")."""
        if name is not None:
            names = [name]
        else:
            # Prompt 677: the whole-base scan enumerates CURRENT knowledge only. Raw all() also returns
            # explicitly inactive records (Prompt 663); they used to fill the max_entities budget, so a
            # real contradiction among active records could be left unchecked while the result still
            # said "consistent", and inactive names were reported as "checked". The status filter runs
            # BEFORE the cap. An explicit `name` is checked as asked (its rows are still current-only
            # via contradictions_for). all() itself is unchanged.
            names = [row["name"] for row in self.knowledge.all() if row.get("status") != "inactive"][:max_entities]

        all_contradictions = []
        for n in names:
            all_contradictions.extend(self.contradictions_for(n))

        return {
            "checked": names,
            "contradictions": all_contradictions,
            "consistent": not all_contradictions,
        }

    # ------------------------------------------------------------------
    # Conversational helper
    # ------------------------------------------------------------------
    def summarize_relationships(self, name, limit=5):
        """Human-readable, one-fact-per-line summary of what is known
        about `name` purely from relationships (not its description).
        Returns None if nothing relational is known about it at all -
        callers should fall back to an honest "I don't know" in that
        case rather than presenting an empty summary as an answer."""
        rels = self._current_rels(name)
        lines = []
        for rel in rels["outgoing"][:limit]:
            lines.append(phrase_relation(name, rel["relation_type"], rel["to_name"]))
        for rel in rels["incoming"][:limit]:
            lines.append(phrase_relation(rel["from_name"], rel["relation_type"], name))
        if not lines:
            return None
        return " ".join(lines)

    # ==================================================================
    # Stage 5: the reason() pipeline
    # ==================================================================
    def reason(self, query, context=None, max_depth=DEFAULT_MAX_INFERENCE_DEPTH,
               max_rules=DEFAULT_MAX_RULES_EVALUATED, max_facts=DEFAULT_MAX_FACTS_INSPECTED,
               request_forms=False):
        """Run the full QUERY PARSING -> CONTEXT RESOLUTION -> KNOWLEDGE
        RETRIEVAL -> REASONING pipeline over `query` (a natural-language
        question, or a bare entity name) and return a ReasoningResult.

        `context`, if given (a context.conversation_context.
        ConversationContext, or anything exposing the same
        `recent_entries()` interface), lets a reference word ("it",
        "this") used as the query's subject be resolved against recent
        conversation - see context/reference_resolution.py. Without a
        context, a bare reference word cannot be resolved and the
        result is STATUS_AMBIGUOUS, never a guess.

        `request_forms=True` (Prompt 631, opt-in; default False keeps
        the previous parse) also understands request-form questions
        such as "Tell me about X", "Explain X", "What's X?" and a
        leading "please" - see query_parsing.parse_query.

        Never raises: any internal failure is caught and reported as a
        warning on the returned result rather than propagating, since a
        conversational reasoning call should never crash the caller.
        """
        result = ReasoningResult(query=query)
        try:
            self._reason(result, query, context, max_depth, max_rules, max_facts,
                         request_forms=request_forms)
        except Exception as e:  # reasoning must never crash the caller
            result.warnings.append(f"reasoning_error: {e}")
            result.status = STATUS_UNKNOWN
            result.unknowns.append("An internal error prevented reasoning about that.")
        return result

    def _reason(self, result, query, context, max_depth, max_rules, max_facts,
                request_forms=False):
        budget = Budget(max_depth, max_rules, max_facts)

        # --- QUERY PARSING ------------------------------------------------
        parsed = parse_query(query, request_forms=request_forms)
        result.add_step("parsed query", intent=parsed.intent, subject=parsed.subject, relation=parsed.relation)

        subject = parsed.subject
        if not subject:
            result.status = STATUS_UNKNOWN
            result.unknowns.append("No subject could be identified in that question.")
            return

        # --- CONTEXT RESOLUTION --------------------------------------------
        subject, resolved = self._resolve_subject(subject, context, result)
        if not resolved:
            return  # ambiguous / unresolved reference - result already set

        obj = parsed.object
        if obj:
            obj, obj_resolved = self._resolve_subject(obj, context, result)
            if not obj_resolved:
                return

        # --- KNOWLEDGE RETRIEVAL --------------------------------------------
        # Prompt 667: only CURRENT knowledge may answer. Explicitly inactive records (Prompt 663)
        # are not candidates; if nothing current matches but an inactive record does, the
        # existing "not in the knowledge base" outcome is returned (no description, relationship,
        # inference or contradiction is read for it). lookup()/raw retrieval keep their contract.
        resolution = self.knowledge.resolve_current_name(subject)
        if resolution["status"] == "inactive":
            result.add_step("knowledge retrieval", subject=subject, found=False)
            result.status = STATUS_UNKNOWN
            result.unknowns.append(f"'{subject}' is not in the knowledge base yet.")
            result.add_step("direct lookup failed")
            return
        entry = resolution["record"]
        canonical = entry["name"] if entry else subject
        result.add_step("knowledge retrieval", subject=canonical, found=bool(entry))
        if entry:
            result.supporting_facts.append(entry)

        # --- REASONING --------------------------------------------------------
        if parsed.intent == INTENT_WHAT_IS:
            self._reason_what_is(result, canonical, entry, budget)
        elif parsed.intent in (INTENT_RELATION_QUERY, INTENT_VERIFY_RELATION, INTENT_VERIFY_IS_A):
            self._reason_relation(result, canonical, parsed.relation, obj, budget)
        else:  # INTENT_GENERIC - the ASK-style catch-all
            self._reason_generic(result, canonical, entry, budget)

        # --- CONTRADICTION CHECK (always run, regardless of intent) --------
        contradictions = self.contradictions_for(canonical)
        if contradictions:
            result.contradictions = [{"a": a, "b": b} for a, b in contradictions]
            result.add_step("contradiction check", found=len(contradictions))
            contradicted_relations = set()
            for a, b in contradictions:
                contradicted_relations.add(a["relation_type"])
                contradicted_relations.add(b["relation_type"])

            if result.status == STATUS_UNKNOWN:
                # We couldn't answer AND the stored knowledge about this
                # subject is internally inconsistent - say so plainly
                # rather than leaving it as a bare "unknown".
                result.status = STATUS_CONTRADICTION
            elif (
                result.status == STATUS_ANSWERED and result.conclusion
                and result.conclusion["relation"] in contradicted_relations
            ):
                # The specific fact we were about to answer with IS one
                # side of a direct contradiction - item 10: "must NOT
                # silently choose one without evidence [for which side
                # is right]". Withdraw the confident single answer in
                # favor of reporting the conflict.
                result.status = STATUS_CONTRADICTION
                result.answer = None
                result.confidence = 0.0
                result.add_step("answer withdrawn due to contradiction", relation=result.conclusion["relation"])

        if budget.limit_hit and result.status == STATUS_UNKNOWN:
            result.status = STATUS_LIMIT_REACHED

    # ------------------------------------------------------------------
    # Context-aware subject/object resolution
    # ------------------------------------------------------------------
    def _resolve_subject(self, text, context, result):
        """Returns (resolved_text, ok). ok=False means `result` has
        already been finalized (STATUS_AMBIGUOUS) and the caller should
        stop. A word that isn't a recognized reference at all (the
        common case - "Python") is returned unchanged."""
        # Imported lazily (not at module top) so the Reasoning Engine has
        # no hard/circular import-time dependency on the context package
        # for the (still fully supported) context=None call shape - same
        # convention as understanding/engine.py's own lazy import of this
        # exact function.
        from context.reference_resolution import resolve_reference

        is_reference_word = text.strip().lower() in _REFERENCE_WORDS
        if context is None:
            if is_reference_word:
                result.add_step("context resolution skipped", reason="no_context_supplied")
                result.status = STATUS_AMBIGUOUS
                result.unknowns.append(f"'{text}' refers to something, but no conversation context was given.")
                return text, False
            return text, True

        resolution = resolve_reference(text, context)
        if resolution is None:
            return text, True  # not a reference word at all - nothing to resolve

        result.add_step(
            "context resolution", reference=text, resolved=resolution.resolved_entity,
            ambiguous=resolution.ambiguous, confidence=round(resolution.confidence, 4),
        )
        if resolution.ambiguous or not resolution.resolved_entity:
            result.status = STATUS_AMBIGUOUS
            result.unknowns.append(f"'{text}' is ambiguous - not enough recent context to resolve it safely.")
            return text, False

        return resolution.resolved_entity, True

    # ------------------------------------------------------------------
    # "What is X?" - direct description, falling back to a direct IS_A
    # relationship if no description has been taught yet.
    # ------------------------------------------------------------------
    def _reason_what_is(self, result, subject, entry, budget):
        if entry and entry.get("description"):
            result.status = STATUS_ANSWERED
            result.answer = entry["description"]
            result.conclusion = {"subject": subject, "relation": "DESCRIBED_AS", "object": entry["description"]}
            result.confidence = entry.get("confidence") or DEFAULT_FACT_CONFIDENCE
            result.add_step("direct lookup", source="description")
            return

        outgoing = self._current_rels(subject)["outgoing"]
        is_a = next((r for r in outgoing if r["relation_type"] == "IS_A"), None)
        if is_a:
            result.status = STATUS_ANSWERED
            result.answer = f"{subject} is a {is_a['to_name']}."
            result.conclusion = {"subject": subject, "relation": "IS_A", "object": is_a["to_name"]}
            result.supporting_relationships.append(is_a)
            result.confidence = _fact_confidence(is_a)
            result.add_step("direct lookup", source="IS_A relationship")
            return

        result.status = STATUS_UNKNOWN
        result.unknowns.append(f"'{subject}' is not in the knowledge base yet.")
        result.add_step("direct lookup failed")

    # ------------------------------------------------------------------
    # "What does X use?" / "Does X use Y?" / "Is X a Y?" - a specific
    # relation_type is wanted, optionally against a specific object.
    # ------------------------------------------------------------------
    def _reason_relation(self, result, subject, relation_type, obj, budget):
        if not relation_type:
            result.status = STATUS_UNKNOWN
            result.unknowns.append("Could not determine what relationship this question is asking about.")
            return

        outgoing = self._current_rels(subject)["outgoing"]
        direct_matches = [r for r in outgoing if r["relation_type"] == relation_type]
        direct = None
        if obj:
            direct = next((r for r in direct_matches if r["to_name"] == obj), None)
        elif direct_matches:
            direct = direct_matches[0]

        if direct:
            result.status = STATUS_ANSWERED
            result.answer = phrase_relation(subject, relation_type, direct["to_name"])
            result.conclusion = {"subject": subject, "relation": relation_type, "object": direct["to_name"]}
            result.supporting_relationships.append(direct)
            result.confidence = _fact_confidence(direct)
            result.add_step("direct lookup", relation=relation_type, to=direct["to_name"])
            return

        # No direct fact - try inference.
        inferred = self._infer(subject, relation_type, obj, budget, result)
        if inferred:
            result.status = STATUS_ANSWERED
            inferred_sentence = phrase_relation(inferred.from_name, inferred.relation_type, inferred.to_name)
            # Keep the "(inferred)" marker the direct-lookup answer above
            # never has, so a caller/test can tell the two apart from the
            # answer text alone - drop the trailing period first so the
            # marker doesn't land after it (e.g. "...language. (inferred)").
            result.answer = f"{inferred_sentence.rstrip('.')} (inferred)."
            result.conclusion = {
                "subject": inferred.from_name, "relation": inferred.relation_type,
                "object": inferred.to_name,
            }
            result.supporting_relationships.extend(inferred.supporting_relationships)
            if inferred.rule_name:
                result.rules_used.append(inferred.rule_name)
            result.confidence = inferred.confidence
            result.add_step(
                "inference", relation=relation_type, to=inferred.to_name,
                rule=inferred.rule_name, depth=inferred.depth,
                provenance=inferred.provenance(),
            )
            return

        result.status = STATUS_LIMIT_REACHED if budget.limit_hit else STATUS_UNKNOWN
        target = f" '{obj}'" if obj else ""
        result.unknowns.append(f"No knowledge relates '{subject}' to{target} via '{relation_type}'.")
        result.add_step("inference failed", relation=relation_type, limit_hit=budget.limit_hit)

    # ------------------------------------------------------------------
    # Bare-name / catch-all query - the ASK-equivalent used when the
    # question didn't parse into a specific relation.
    # ------------------------------------------------------------------
    def _reason_generic(self, result, subject, entry, budget):
        if entry and entry.get("description"):
            result.status = STATUS_ANSWERED
            result.answer = entry["description"]
            result.conclusion = {"subject": subject, "relation": "DESCRIBED_AS", "object": entry["description"]}
            result.confidence = entry.get("confidence") or DEFAULT_FACT_CONFIDENCE
            result.add_step("direct lookup", source="description")
            return

        summary = self.summarize_relationships(subject)
        if summary:
            result.status = STATUS_ANSWERED
            result.answer = summary
            rels = self._current_rels(subject)
            result.supporting_relationships.extend(rels["outgoing"] + rels["incoming"])
            confidences = [_fact_confidence(r) for r in rels["outgoing"] + rels["incoming"]]
            result.confidence = min(confidences) if confidences else DEFAULT_FACT_CONFIDENCE
            result.add_step("direct lookup", source="relationships")
            return

        result.status = STATUS_UNKNOWN
        result.unknowns.append(f"'{subject}' is not in the knowledge base yet.")
        result.add_step("direct lookup failed")

    # ==================================================================
    # Inference: transitive-relation closure + rule engine
    # ==================================================================
    def _infer(self, subject, relation_type, obj, budget, result):
        """Try every applicable inference mechanism for
        (subject, relation_type, ?) and return the first InferredFact
        found (optionally constrained to end at `obj`), or None.
        Bounded by `budget` throughout - see Budget/DEFAULT_MAX_*."""
        if relation_type in TRANSITIVE_RELATION_TYPES:
            inferred = self._transitive_closure(subject, relation_type, obj, budget)
            if inferred:
                return inferred

        for rule in self.rules.rules_for_relation(relation_type):
            if not budget.take_rule():
                result.warnings.append("reasoning_limit: max_rules_evaluated reached")
                break
            inferred = self._try_rule(rule, subject, budget)
            if inferred and (obj is None or inferred.to_name == obj):
                return inferred

        return None

    def _transitive_closure(self, subject, relation_type, obj, budget):
        """Cycle-safe, depth-bounded BFS along edges of a single
        relation_type (item 5: "an extensible mechanism for declaring
        which relationship types support which inference behavior").
        Stops as soon as `obj` is reached (if given), or - for an open
        query - returns the first reachable node beyond a direct hop
        (depth >= 2; a depth-1 hop is a direct fact, already handled
        by the direct-lookup step before this is ever called)."""
        visited = {subject}
        frontier = [(subject, [], 0)]

        for depth in range(1, budget.max_depth + 1):
            next_frontier = []
            for node, path, _prev_depth in frontier:
                if not budget.take_fact():
                    return None
                outgoing = self._current_rels(node)["outgoing"]
                for rel in outgoing:
                    if rel["relation_type"] != relation_type:
                        continue
                    new_path = path + [rel]
                    target = rel["to_name"]
                    if depth >= 2 and (obj is None or target == obj):
                        confidences = [_fact_confidence(r) for r in new_path]
                        return InferredFact(
                            from_name=subject, relation_type=relation_type, to_name=target,
                            confidence=_depth_confidence(confidences, depth),
                            depth=depth, supporting_relationships=new_path, rule_name=None,
                        )
                    if target not in visited:
                        visited.add(target)
                        next_frontier.append((target, new_path, depth))
            frontier = next_frontier
            if not frontier:
                break
        else:
            # The loop ran through every allowed depth without breaking
            # early (i.e. without exhausting the graph) - there was more
            # left to explore that max_depth simply didn't allow. This
            # is a genuine "the limit stopped us", not proof no answer
            # exists - see reason()'s STATUS_LIMIT_REACHED handling.
            if frontier:
                budget.limit_hit = True

        return None

    def _try_rule(self, rule, subject, budget, bindings=None, premise_index=0, facts_used=None):
        """Attempt to satisfy `rule`'s premises in order, starting with
        its first premise's from-variable bound to `subject`. Bounded
        backtracking: if a premise has more than one matching outgoing
        relationship, each is tried in turn (still counted against
        `budget`), so a rule can find a satisfying chain without
        exploring the whole graph unboundedly."""
        if bindings is None:
            bindings = {rule.premises[0][0]: subject}
            facts_used = []

        if premise_index >= len(rule.premises):
            concl_from_var, concl_rel, concl_to_var = rule.conclusion
            concl_from = bindings.get(concl_from_var)
            concl_to = bindings.get(concl_to_var)
            if concl_from is None or concl_to is None:
                return None
            confidences = [_fact_confidence(f) for f in facts_used]
            return InferredFact(
                from_name=concl_from, relation_type=concl_rel, to_name=concl_to,
                confidence=_depth_confidence(confidences, len(facts_used), weight=rule.weight),
                depth=len(facts_used), supporting_relationships=list(facts_used), rule_name=rule.name,
                rule_id=getattr(rule, "id", None), bindings=dict(bindings),
            )

        var_a, rel_type, var_b = rule.premises[premise_index]
        if var_a not in bindings:
            return None  # rule authoring constraint: each premise's subject must already be bound

        entity_a = bindings[var_a]
        if not budget.take_fact():
            return None
        outgoing = self._current_rels(entity_a)["outgoing"]
        candidates = [r for r in outgoing if r["relation_type"] == rel_type]

        for rel in candidates:
            if var_b in bindings and bindings[var_b] != rel["to_name"]:
                continue  # inconsistent with an earlier binding of the same variable
            new_bindings = dict(bindings)
            new_bindings[var_b] = rel["to_name"]
            outcome = self._try_rule(
                rule, subject, budget, bindings=new_bindings,
                premise_index=premise_index + 1, facts_used=facts_used + [rel],
            )
            if outcome:
                return outcome

        return None

    # ==================================================================
    # Rule inspection / explanation (items 18, 20)
    # ==================================================================
    def explain_rule(self, rule_name):
        """Full metadata for a rule this engine would actually evaluate,
        by name - the registry-backed record if a RuleRegistry was
        supplied (id, priority, source, version, timestamps, etc.), or a
        plain Rule's own to_dict() otherwise. Returns None if no such rule
        is currently registered. Never fabricates an explanation (item 20)
        - everything returned came from either storage or the Rule object
        itself, not from re-deriving/guessing."""
        if self.rule_registry is not None:
            record = self.rule_registry.get_by_name(rule_name)
            if record:
                return record
        rule = self.rules.get_by_name(rule_name) if hasattr(self.rules, "get_by_name") else None
        return rule.to_dict() if rule else None
