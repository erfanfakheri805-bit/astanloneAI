# Prompt 640 - Confidence/evidence metadata integrity (Section 3)

Result: inspection showed the existing implementation already satisfies every
requirement, so no production code changed; behaviour is pinned by
`tests/test_knowledge_confidence_integrity_prompt640.py`.

Existing semantics (unchanged)
- `learn()/teach()/correct()`: `confidence=None` on an update keeps the stored
  value; an explicit value (including 0.0) replaces it; an effectively
  identical operation is a true no-op (no write, no version bump, no event).
- `knowledge.confidence` is `REAL NOT NULL DEFAULT 1.0` (schema). A NEW entry
  created without a confidence - including a stub auto-created by `relate()`
  - is therefore stored at 1.0. That is the documented KnowledgeSystem policy,
  applied once at creation and never re-applied on later operations.
- `relationships.confidence` is nullable: a missing value stays NULL (never
  defaulted) and is exposed as None by retrieval/context; `relate()` keeps the
  Prompt 636 idempotency/metadata-preservation rules.
- Validation lives in the consumers, not at storage: the learned-knowledge
  gate ignores confidences that are not numbers in [0.0, 1.0] and treats None
  as its documented 1.0 fallback (decision only, never written back); the NL
  learning decision rejects too-low confidence. Storage accepts values as given.
- `learning_events` record the description transition (+ source) only; they
  hold no confidence and are never read as current confidence.

Limitations
- Because the column is NOT NULL, "confidence unknown" cannot be represented
  on a knowledge row; the 1.0 default is indistinguishable from an explicit 1.0.
  Changing that would need a schema change, which is out of scope.
- Storage does not validate range/type (out-of-range values are stored as
  given and only rejected downstream by the gate).
- Learning events do not record confidence changes.
