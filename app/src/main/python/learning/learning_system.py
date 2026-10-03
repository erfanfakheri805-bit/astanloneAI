"""
Learning System
=================
The Learning System is the single entry point through which new
knowledge enters the application - whether it arrives via an AEL TEACH/
RELATE instruction, or via the natural-language pipeline below. It owns
no storage itself; it delegates to the Concept/Knowledge System, keeping
a clean separation between "how learning is triggered", "what should be
learned" and "how knowledge is stored":

    Understanding   = interpretation (understanding/engine.py)
    Learning        = deciding what to learn, and storing it (this file)
    Knowledge       = persistent structured information (knowledge/, concepts/)

Two optional collaborators, both backwards compatible (omit either and
the system still works, just without that extra behaviour):

- `memory`: if given, every TEACH/RELATE is recorded as a row in the
  `learning_events` table - real episodic learning history, not just
  the end state.
- `reasoning_engine`: if given, every RELATE is checked against the
  (small, explicit) set of known contradictory relation pairs before
  being stored. The relationship is still stored either way - this
  stage surfaces contradictions for a human or a future stage to
  resolve, it does not silently overwrite or fabricate a resolution.
- `learning_record_store`: if given, `get_learning_analysis()` below
  reads it (via `LearningRecordStore.get_all()`) and returns a
  `LearningAnalyzer` summary of what it currently holds. Nothing in
  this module ever writes to it - no code path here creates a
  `LearningRecord` on its own initiative; a `LearningRecordStore` is
  only ever populated by whatever separate caller already owns that
  responsibility. Omitting it (the default) leaves
  `get_learning_analysis()` returning the normal zero-value analysis.

Natural-language learning
--------------------------
`learn_from_understanding()` is the "LEARNING ENGINE" box in the
project's pipeline:

    UNDERSTANDING RESULT -> LEARNING ENGINE -> KNOWLEDGE VALIDATION
        -> CONCEPT / RELATION STORAGE -> PERSISTENT KNOWLEDGE

It never re-parses raw text - it consumes the structured LearningInput
objects built from an UnderstandingResult (see learning_input.py), runs
each one through the Learning Decision step (learning_decision.py), and
only persists the ones that decision approves, via the exact same
teach()/relate() calls AEL uses. Both paths converge here:

    AEL              -> AEL Interpreter   -> teach()/relate() -----v
    Natural language -> Understanding Eng -> learn_from_understanding() -> teach()/relate() -> Knowledge/Concept System
"""

import contextlib

from .learning_input import build_learning_inputs
from .learning_decision import LearningDecisionEngine
from .learning_result import LearningResult
from .learning_analyzer import LearningAnalyzer


class LearningSystem:
    def __init__(self, concept_system, knowledge_system, memory=None, reasoning_engine=None,
                 learning_record_store=None):
        self.concepts = concept_system
        self.knowledge = knowledge_system
        self.memory = memory
        self.reasoning = reasoning_engine
        self.learning_record_store = learning_record_store

    # ------------------------------------------------------------------
    # Low-level learning primitives - shared by AEL and the
    # natural-language pipeline below.
    # ------------------------------------------------------------------
    def _atomic(self):
        """Prompt 645: one transaction for a knowledge mutation and its
        learning event. Only when both go through the same store (a real
        MemorySystem); otherwise behaviour is exactly as before."""
        mem = self.memory
        fn = getattr(type(mem), "_atomic", None) if mem else None
        if callable(fn) and mem is getattr(self.knowledge, "memory", None):
            return fn(mem)
        return contextlib.nullcontext()

    def teach(self, name, description, source="ael", confidence=None, source_text=None, learning_method=None):
        with self._atomic():
            return self._teach(name, description, source=source, confidence=confidence,
                               source_text=source_text, learning_method=learning_method)

    def correct(self, name, description, source=None, confidence=None, source_text=None,
                learning_method=None):
        with self._atomic():
            return self._correct(name, description, source=source, confidence=confidence,
                                 source_text=source_text, learning_method=learning_method)

    def set_status(self, name, status, source=None, source_text=None, learning_method=None):
        with self._atomic():
            return self._set_status(name, status, source=source, source_text=source_text,
                                    learning_method=learning_method)

    def _set_status(self, name, status, source=None, source_text=None, learning_method=None):
        """Prompt 663: retire / reactivate an existing knowledge record (see
        KnowledgeSystem.set_status). Returns the record, or None if `name` is unknown (nothing is
        created). A real transition writes one "status" event - target = stored name, detail =
        "'<old>' -> '<new>'", source = the PERSISTED source; a no-op writes nothing."""
        before = None
        if isinstance(name, str):
            before = self.knowledge.find_by_name_case_insensitive(name)
        entry = self.knowledge.set_status(name, status, source=source, source_text=source_text,
                                          learning_method=learning_method)
        changed = (entry is not None and before is not None and entry["version"] != before["version"])
        if changed and self.memory:
            self.memory.add_learning_event(
                "status", entry["name"], detail=f"{before['status']!r} -> {entry['status']!r}",
                source=entry["source"],
            )
        return entry

    def relate(self, from_name, to_name, relation_type, source="ael", confidence=None,
               source_text=None, learning_method=None):
        with self._atomic():
            return self._relate(from_name, to_name, relation_type, source=source,
                                confidence=confidence, source_text=source_text,
                                learning_method=learning_method)

    def _teach(self, name, description, source="ael", confidence=None, source_text=None, learning_method=None):
        before = self.knowledge.get(name) if isinstance(name, str) else None
        entry = self.concepts.define(
            name, description, source=source, confidence=confidence,
            source_text=source_text, learning_method=learning_method,
        )
        # Prompt 632: an identical repeat changed nothing (same version),
        # so it is not logged as a second learning event.
        unchanged = before is not None and entry["version"] == before["version"]
        if self.memory and not unchanged:
            self.memory.add_learning_event("teach", name, detail=description, source=source)
        return entry

    def _correct(self, name, description, source=None, confidence=None, source_text=None,
                 learning_method=None):
        """Prompt 633/635: explicitly correct an existing knowledge
        record (see KnowledgeSystem.correct). Returns the updated
        record, or None if `name` is unknown (nothing is created). The
        replaced description is preserved in the learning-event
        history.

        `source` defaults to None, not a hardcoded value: this thin
        wrapper must not silently override the provenance semantics
        KnowledgeSystem.correct() documents ("None = keep what is
        stored"). A caller that wants the correction attributed to a
        specific source (e.g. Core._apply_resolved_correction_to_
        knowledge passing source="user_correction") still gets that -
        this only stops an *unspecified* source from clobbering
        whatever provenance the record already had."""
        before = None
        if isinstance(name, str):
            before = self.knowledge.get(name) or self.knowledge.find_by_name_case_insensitive(name)
        entry = self.knowledge.correct(
            name, description, source=source, confidence=confidence,
            source_text=source_text, learning_method=learning_method,
        )
        changed = (entry is not None and before is not None
                   and before["name"] == entry["name"] and entry["version"] != before["version"])
        if changed and self.memory:
            self.memory.add_learning_event(
                "correct", entry["name"],
                detail=f"{before['description']!r} -> {entry['description']!r}",
                # Prompt 644: log the PERSISTED source (correct() keeps the
                # stored one when `source` is None), not the raw argument.
                source=entry["source"],
            )
        return entry

    def _relate(self, from_name, to_name, relation_type, source="ael", confidence=None,
                source_text=None, learning_method=None):
        """Returns {"created": bool, "contradiction": row-or-None}.

        Prompt 636: an exactly identical repeated relationship (see
        KnowledgeSystem.relate - effective values, not raw arguments,
        with the existing None-preserving semantics) is a true no-op at
        this layer too: no second "relate" learning event is recorded.
        KnowledgeSystem.relate()/ConceptSystem.link() only ever surface
        a created/not-created bool (no separate changed/unchanged
        signal - changing that would ripple into every other caller of
        the documented True/False contract), so this compares the
        stored relationship row before and after the call to tell a
        genuine update apart from a no-op, without duplicating or
        second-guessing the no-op decision KnowledgeSystem.relate()
        already made.
        """
        contradiction = None
        if self.reasoning:
            contradiction = self.reasoning.check_new_relationship(from_name, relation_type, to_name)

        before = self.knowledge.memory.query_one(
            "SELECT * FROM relationships WHERE from_name = ? AND to_name = ? AND relation_type = ?",
            (from_name, to_name, relation_type),
        )

        created = self.concepts.link(
            from_name, to_name, relation_type,
            confidence=confidence, source_type=source, source_text=source_text,
            learning_method=learning_method,
        )

        after = self.knowledge.memory.query_one(
            "SELECT * FROM relationships WHERE from_name = ? AND to_name = ? AND relation_type = ?",
            (from_name, to_name, relation_type),
        )
        changed = created or before is None or dict(before) != dict(after)

        if self.memory and changed:
            self.memory.add_learning_event(
                "relate", from_name, detail=f"{relation_type} -> {to_name}",
                # Prompt 644: persisted relationship source (None argument keeps stored value).
                source=after["source_type"] if after is not None else source,
            )

        return {"created": created, "contradiction": contradiction}

    def recall(self, name):
        return self.concepts.get_with_relations(name)

    def search(self, term):
        return self.knowledge.search(term)

    # ------------------------------------------------------------------
    # Learning record analysis (read-only)
    # ------------------------------------------------------------------
    def get_learning_analysis(self):
        """A read-only summary of whatever `LearningRecord` objects
        this system's `learning_record_store` currently holds, via the
        existing `LearningAnalyzer` - reusing both existing components
        rather than duplicating their logic here.

        Never reads or writes `self.concepts`/`self.knowledge`, never
        creates a `LearningRecord`, and never mutates
        `learning_record_store` or anything in it - it only ever calls
        the store's own `get_all()` (which already returns safe
        copies) and hands that list to `LearningAnalyzer.analyze()`.

        Returns the normal zero-value analysis
        (`{"total_records": 0, "average_confidence": 0.0,
        "highest_confidence": 0.0}`) when no `learning_record_store`
        was given to this `LearningSystem`, or when that store is
        empty."""
        analyzer = LearningAnalyzer()
        if self.learning_record_store is None:
            return analyzer.analyze([])
        return analyzer.analyze_store(self.learning_record_store)

    # ------------------------------------------------------------------
    # Concept identity resolution
    # ------------------------------------------------------------------
    def _resolve_concept_name(self, candidate_name):
        """Resolve a candidate concept name (pulled out of free text by
        the Understanding Engine) against what already exists, so
        "Python" and "python" identify the same concept instead of
        silently becoming two. Exact match first (cheap, and preserves
        whatever casing is already canonical); case-insensitive match
        second. If nothing matches at all, the candidate's own text is
        returned unchanged and will become the concept's canonical,
        human-readable display name the first time it's stored - this
        function itself never writes anything.

        Returns (canonical_name, is_new: bool).
        """
        name = (candidate_name or "").strip()
        existing = self.knowledge.get(name)
        if existing:
            return existing["name"], False
        existing_ci = self.knowledge.find_by_name_case_insensitive(name)
        if existing_ci:
            return existing_ci["name"], False
        return name, True

    # ------------------------------------------------------------------
    # Natural-language learning pipeline
    # ------------------------------------------------------------------
    def learn_from_understanding(self, understanding_result, source_text=None, auto_commit=True,
                                  source="understanding_engine"):
        """Run the full UNDERSTANDING RESULT -> LEARNING ENGINE ->
        KNOWLEDGE VALIDATION -> CONCEPT/RELATION STORAGE pipeline over
        one UnderstandingResult and return a LearningResult.

        `source_text` defaults to the original text the Understanding
        Engine was given (understanding_result.original_text) - passing
        it explicitly only matters if a caller wants to record different
        provenance text than what was analyzed (uncommon).

        `auto_commit=False` runs the exact same understanding ->
        candidate-building -> decision pipeline, but stops before
        writing anything: every candidate that the decision step would
        have approved is instead reported as a skipped_item with reason
        "preview_only". This is the "review before writing" mode a
        future UI panel can use; Core.learn_from_text() (core/core.py)
        always commits.
        """
        result = LearningResult()
        text = source_text if source_text is not None else understanding_result.original_text
        result.confidence = understanding_result.confidence

        learning_inputs = build_learning_inputs(understanding_result)
        if not learning_inputs:
            result.warnings.append("no_learnable_candidates")
            result.success = True
            return result

        decision_engine = LearningDecisionEngine(self.knowledge, self.reasoning)

        for learning_input in learning_inputs:
            if learning_input.source_text is None:
                learning_input.source_text = text

            try:
                decision = decision_engine.decide(learning_input)
            except Exception as e:  # decision-making itself must never crash learning
                result.errors.append(f"decision_error: {e}")
                continue

            if not decision.should_persist:
                result.skipped_items.append({
                    **learning_input.to_dict(),
                    "reason": decision.reason,
                })
                continue

            if not auto_commit:
                result.skipped_items.append({
                    **learning_input.to_dict(),
                    "reason": "preview_only",
                })
                continue

            try:
                subject_name, subject_is_new = self._resolve_concept_name(learning_input.subject)
                object_name, object_is_new = self._resolve_concept_name(learning_input.object)

                outcome = self.relate(
                    subject_name, object_name, learning_input.relation,
                    source=source, confidence=learning_input.confidence,
                    source_text=learning_input.source_text, learning_method=learning_input.learning_method,
                )
            except Exception as e:
                result.errors.append(f"persist_error: {e}")
                continue

            if subject_is_new:
                result.created_concepts.append(subject_name)
            if object_is_new:
                result.created_concepts.append(object_name)

            item = {
                "subject": subject_name,
                "relation": learning_input.relation,
                "object": object_name,
                "confidence": round(learning_input.confidence, 4) if learning_input.confidence is not None else None,
                "input_type": learning_input.input_type,
            }
            result.learned_items.append(item)
            if outcome["created"]:
                result.created_relationships.append(item)
            else:
                result.updated_items.append(item)

            if outcome["contradiction"]:
                c = outcome["contradiction"]
                result.warnings.append(
                    f"contradiction: '{subject_name}' {learning_input.relation} '{object_name}' conflicts "
                    f"with existing '{c['from_name']}' {c['relation_type']} '{c['to_name']}'"
                )

        result.success = not result.errors
        return result

    def ingest_understanding(self, result, auto_commit=False, source="understanding_engine"):
        """Backwards-compatible wrapper around learn_from_understanding()
        for any caller still expecting the original foundation-stage
        return shape (candidate_entities/candidate_relations/taught/
        related). New code should call learn_from_understanding()
        directly for the full LearningResult (created_concepts,
        skipped_items with reasons, warnings, errors, etc).
        """
        if not auto_commit:
            return {
                "committed": False,
                "candidate_entities": list(result.entities),
                "candidate_relations": [r.to_dict() for r in result.relations],
                "taught": [],
                "related": [],
            }

        learning_result = self.learn_from_understanding(result, auto_commit=True, source=source)
        related = [
            {
                "subject": item["subject"],
                "relation": item["relation"],
                "object": item["object"],
                "created": item in learning_result.created_relationships,
                "contradiction": None,
            }
            for item in learning_result.learned_items
        ]
        return {
            "committed": True,
            "candidate_entities": [],
            "candidate_relations": [],
            "taught": [],
            "related": related,
        }
