"""
Conversation Context - Reference Resolution
==============================================
A lightweight, fully local, fully deterministic mechanism for resolving
simple references ("it", "this", "that", "they", "them", "the
language", "this concept", ...) against recent conversational context.

This is explicitly NOT full natural-language coreference resolution -
see the project spec's own warning against that. It is a small scoring
function over a handful of real, inspectable signals:

    - recency          (how many entries back the candidate was seen)
    - grammatical role  (was the candidate the *subject* of a recent
                          relation - a much more likely antecedent than
                          an incidental object)
    - semantic compatibility (for a generic reference like "the
                          language", does a candidate's own text or its
                          most recent relation object actually contain
                          that noun?)
    - grammatical number (singular reference vs. plural candidate)

None of this is "if text contains 'it': assume <hardcoded concept>" -
every resolution is produced from the actual recent context handed in,
and there is no result at all (never a guess) once candidates are
absent or too close to call. See `_AMBIGUITY_MARGIN` below for exactly
what "too close to call" means.
"""

SINGULAR_PRONOUNS = {"it", "this", "that"}
PLURAL_PRONOUNS = {"they", "them", "these", "those"}
_ALL_SIMPLE_PRONOUNS = SINGULAR_PRONOUNS | PLURAL_PRONOUNS

# Generic nouns a demonstrative ("this X" / "that X" / "the X") can
# refer back to a recently mentioned concept through, e.g. "the
# language" after "Python is a programming language.". Intentionally
# small and easy to extend - see module docstring.
GENERIC_REFERENCE_NOUNS = {
    "language", "system", "concept", "project", "tool", "thing", "one",
}
_DEMONSTRATIVE_PREFIXES = ("this ", "that ", "the ")

# Deterministic scoring weights - fixed contributions from actual
# signals, never randomized. Same style as understanding/engine.py's
# own confidence weights.
_RECENCY_DECAY = 0.15
_WEIGHT_RECENCY = 0.1
_WEIGHT_RECENT_SUBJECT = 0.5
_WEIGHT_SEMANTIC_MATCH = 0.6
_WEIGHT_GRAMMAR_NUMBER = 0.1

# How much stronger the best candidate must score than the next-best
# one before it is treated as resolved rather than ambiguous. Chosen so
# that two independently-introduced, equally-prominent recent subjects
# (e.g. "Python uses indentation. Java uses braces. It is popular.")
# stay ambiguous rather than being resolved by recency alone.
_AMBIGUITY_MARGIN = 0.2

_MAX_CANDIDATE_ENTRIES = 6
_MAX_REPORTED_CANDIDATES = 3


class ReferenceResolution:
    """Structured trace of one reference-resolution attempt - the
    "debugging / trace information" the spec calls for: original
    reference, candidates considered, what (if anything) was selected,
    confidence, and why."""

    def __init__(self, reference_text, candidates, resolved_entity, confidence, ambiguous, reason):
        self.reference_text = reference_text
        self.candidates = candidates  # list of {"text": str, "score": float}
        self.resolved_entity = resolved_entity  # str or None
        self.confidence = confidence
        self.ambiguous = ambiguous
        self.reason = reason

    def __repr__(self):
        return (
            f"ReferenceResolution({self.reference_text!r} -> {self.resolved_entity!r}, "
            f"ambiguous={self.ambiguous}, confidence={self.confidence:.2f})"
        )

    def to_dict(self):
        return {
            "reference_text": self.reference_text,
            "candidates": self.candidates,
            "resolved_entity": self.resolved_entity,
            "confidence": round(self.confidence, 4),
            "ambiguous": self.ambiguous,
            "reason": self.reason,
        }


def _classify_reference(text):
    """Return (is_reference, is_plural, generic_noun). generic_noun is
    only set for a "this/that/the <known noun>" phrase; simple pronouns
    have no associated noun."""
    t = (text or "").strip().lower()
    if not t:
        return False, False, None
    if t in _ALL_SIMPLE_PRONOUNS:
        return True, t in PLURAL_PRONOUNS, None
    for prefix in _DEMONSTRATIVE_PREFIXES:
        if t.startswith(prefix):
            noun = t[len(prefix):].strip()
            if noun in GENERIC_REFERENCE_NOUNS:
                return True, False, noun
    return False, False, None


def _collect_candidates(context):
    """Recent entities, most-recent-entry-first, deduplicated
    case-insensitively (first/most-recent occurrence wins). Each
    candidate carries the recency rank of the entry it came from, its
    grammatical role in that entry (was it a relation's subject?), and
    - if it was a subject - the object of that relation, for semantic
    matching (e.g. "the language" -> Python, whose relation object was
    "programming language")."""
    entries = context.recent_entries(limit=_MAX_CANDIDATE_ENTRIES)
    entries = list(reversed(entries))  # most recent first

    candidates = []
    seen = set()
    for rank, entry in enumerate(entries):
        subjects = {
            rel["subject"].strip().lower(): rel.get("object")
            for rel in entry.relations
            if rel.get("subject")
        }
        for ent in entry.entities:
            text = (ent.get("text") or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            is_subject = key in subjects
            candidates.append({
                "text": text,
                "role": "subject" if is_subject else "entity",
                "related_object": subjects.get(key),
                "rank": rank,
            })
    return candidates


def resolve_reference(reference_text, context):
    """Attempt to resolve `reference_text` against `context`.

    Returns None if `reference_text` is not a recognized reference
    phrase at all (the caller should leave it untouched - this is not
    "every unknown word is a pronoun"). Returns a ReferenceResolution
    otherwise, which may itself report `ambiguous=True` with
    `resolved_entity=None` - see module docstring."""
    is_ref, is_plural, generic_noun = _classify_reference(reference_text)
    if not is_ref:
        return None

    candidates = _collect_candidates(context)
    if not candidates:
        return ReferenceResolution(reference_text, [], None, 0.0, True, "no_candidates")

    scored = []
    for cand in candidates:
        score = 0.0
        signals = []

        recency_score = max(0.0, 1.0 - cand["rank"] * _RECENCY_DECAY)
        score += recency_score * _WEIGHT_RECENCY
        signals.append(f"recency:{recency_score:.2f}")

        if cand["role"] == "subject":
            score += _WEIGHT_RECENT_SUBJECT
            signals.append("recent_subject")

        if generic_noun:
            haystacks = [cand["text"].lower()]
            if cand.get("related_object"):
                haystacks.append(cand["related_object"].lower())
            if any(generic_noun in h for h in haystacks):
                score += _WEIGHT_SEMANTIC_MATCH
                signals.append(f"semantic_match:{generic_noun}")

        cand_plural_like = cand["text"].strip().lower().endswith("s")
        if is_plural == cand_plural_like:
            score += _WEIGHT_GRAMMAR_NUMBER
            signals.append("grammar_number_match")

        scored.append((score, cand, signals))

    scored.sort(key=lambda item: -item[0])
    reported = [{"text": c["text"], "score": round(s, 4)} for s, c, _ in scored[:_MAX_REPORTED_CANDIDATES]]

    top_score, top_cand, top_signals = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    if top_score <= 0.0 or (top_score - second_score) < _AMBIGUITY_MARGIN:
        return ReferenceResolution(reference_text, reported, None, top_score, True, "insufficient_margin")

    return ReferenceResolution(
        reference_text, reported, top_cand["text"], min(1.0, top_score), False, ";".join(top_signals)
    )


def resolve_context_references(relations, context):
    """Resolve reference-word subjects/objects within `relations` (a
    list of understanding/relation_extraction.RelationCandidate for the
    *current* sentence) against `context`.

    Returns (resolved_relations, trace):
      - resolved_relations: a new list of RelationCandidate with any
        confidently-resolved reference replaced by the resolved entity
        name. A relation whose subject or object is an *ambiguous*
        reference is dropped entirely - never persisted under its
        literal reference text (e.g. never "it" -> USES -> "indentation")
        and never guessed - the caller (Understanding Engine) still
        gets to see why via `trace`.
      - trace: a list of ReferenceResolution.to_dict() entries, in the
        order references were encountered, for debugging/inspection.
    """
    # Imported lazily to avoid understanding/engine.py and this module
    # forming an import-time dependency cycle worth worrying about -
    # RelationCandidate itself has no dependency on this module.
    from understanding.relation_extraction import RelationCandidate

    resolved = []
    trace = []

    for rel in relations:
        new_subject = rel.subject
        new_object = rel.object
        drop = False

        subj_resolution = resolve_reference(rel.subject, context)
        if subj_resolution is not None:
            trace.append(subj_resolution.to_dict())
            if subj_resolution.ambiguous:
                drop = True
            else:
                new_subject = subj_resolution.resolved_entity

        obj_resolution = resolve_reference(rel.object, context)
        if obj_resolution is not None:
            trace.append(obj_resolution.to_dict())
            if obj_resolution.ambiguous:
                drop = True
            else:
                new_object = obj_resolution.resolved_entity

        if drop:
            continue

        if new_subject != rel.subject or new_object != rel.object:
            resolved.append(RelationCandidate(
                new_subject, rel.relation, new_object,
                pattern=rel.pattern, confidence=rel.confidence,
            ))
        else:
            resolved.append(rel)

    return resolved, trace
