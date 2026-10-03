"""
Language Intelligence - Learned Knowledge Context
========================================================
Prompt 501. One focused, observable capability:

    When the user has explicitly taught the system a piece of learned
    knowledge, the normal response-generation pipeline can be handed
    that knowledge when it is directly relevant to the current user
    message.

    user teaches            Core.learn_from_text() / LearningSystem.teach()
      -> storage            KnowledgeSystem (the existing `knowledge` +
                            `relationships` tables) - unchanged
    later user message
      -> THIS MODULE        `select_learned_knowledge()`: is exactly one
                            stored knowledge entry directly relevant?
      -> understanding      `LanguageUnderstandingResult.
                            learned_knowledge_context` (Core attaches it,
                            the same way it attaches `conversation_state`)
      -> ResponseGenerationContext.learned_knowledge_context
         (response_generation_context.py) / BackendGenerationRequest
         (response_generation_request.py) / `ResponseGenerationRequest.
         generation_context` (response_generation.py) - the one existing
         path every backend, `LocalLanguageModelBackend` included,
         already reads its structured input from.

What this module is NOT
------------------------
No new storage, no second memory system: the knowledge is read through
the EXISTING `KnowledgeSystem` API (`find_by_name_case_insensitive`,
`relationships_for`) - this module never writes, updates or deletes
anything. No embeddings, vector search, fuzzy matching, ranking, LLM or
external service. No answer is generated or inferred: the selected
knowledge is exposed exactly as stored and nothing is added to it.

Deterministic relevance ("direct" relevance only)
--------------------------------------------------
A stored knowledge entry is directly relevant to a message exactly when
the entry's NAME equals (case-insensitively, via the existing
`KnowledgeSystem.find_by_name_case_insensitive`) either

    * one of the message's candidate terms - the existing term
      extraction (`understanding.term_extraction.extract_candidate_terms`,
      already what `Core._find_best_known_concept` uses) - supplied by
      the caller as `candidate_terms`, or
    * a run of 2..MAX_PHRASE_WORDS consecutive words of the message
      (so a taught multi-word name such as "machine learning" can match).

Nothing looser than that (no substring / token-overlap search such as
`KnowledgeSystem.search()`): an entry whose name is not literally in the
message is never a candidate.

An entry only counts as knowledge when it actually carries learned
content - a non-blank `description` or at least one stored relationship
(outgoing or incoming). A bare stub with neither exposes nothing and is
not a candidate.

Prompt 664 - inactive knowledge
--------------------------------
An entry whose stored status is explicitly "inactive" (Prompt 663
lifecycle) is not CURRENT usable knowledge: it is never a candidate, so
it is neither SELECTED nor counted as one of several AMBIGUOUS
candidates. Raw retrieval (get / resolve_name / all / search /
relationships_for / recall) is untouched and still returns it. Any other
status (active, stub, legacy values) behaves exactly as before.
Prompt 670 (supersedes the earlier "rows are never filtered" rule): the
relationship rows carried in the context are CURRENT-only - a row whose other
endpoint is inactive is omitted (stored rows are untouched). An entry whose
only relationships are to inactive endpoints and that has no description
therefore has no current content and is not a candidate.

Statuses (`LearnedKnowledgeSelection.status`)
------------------------------------------------
    SELECTED    exactly one distinct knowledge entry is directly
                relevant; it is carried, unchanged, in `record` /
                `relationships`.
    NOT_FOUND   no directly relevant knowledge entry.
    AMBIGUOUS   two or more distinct entries are directly relevant; none
                is chosen (`candidates` lists their names).
    FAILED      the lookup could not be performed (no knowledge system,
                or it raised); nothing is selected.

Only SELECTED yields a `learned_knowledge_context`. Every other status
leaves the response-generation path exactly as it was before this
stage - the callers (Core) attach nothing.

Prompt 638 - name resolution, provenance, determinism
-------------------------------------------------------
Names are resolved through the deterministic Prompt 637 behaviour of the
existing KnowledgeSystem (`resolve_name`): the lookup uses the casing the
user actually WROTE in the message (candidate terms arrive lower-cased
from term extraction), so an exact-case stored name wins, a single
case-insensitive match resolves, and a name that matches several records
differing only by case is never silently resolved to one of them - it
makes the selection AMBIGUOUS (`candidates` = the competing stored names)
and nothing is attached. The record is exposed exactly as the current
`knowledge` row (so source / source_text / learning_method / confidence
are whatever is stored - never replaced, never invented; a NULL stays
None), the relationships come back in the KnowledgeSystem's fixed order,
and superseded descriptions (learning-event history) are never read.

No mutation
-----------
Everything returned is a deep copy of what the knowledge system
returned; `select_learned_knowledge()` never modifies the message, the
candidate terms, the knowledge system or any stored row, and mutating a
returned selection / its `to_dict()` can never reach back into storage.
"""

import copy
import re

STATUS_SELECTED = "SELECTED"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_FAILED = "FAILED"

# Longest run of consecutive message words tried as a multi-word knowledge
# name, and the most words of a message ever read - both only bound how
# many exact-name lookups one message can cause.
MAX_PHRASE_WORDS = 4
MAX_MESSAGE_WORDS = 64

# The same word definition the existing term extraction / KnowledgeSystem
# tokenizer use.
_WORD_RE = re.compile(r"[A-Za-z0-9_']+")


class LearnedKnowledgeSelection:
    """Plain, read-only result of `select_learned_knowledge()` - same
    value-holder conventions as the rest of language_intelligence/
    (a `to_dict()`, never validating by raising)."""

    def __init__(self, status, message=None, matched_term=None, record=None,
                 relationships=None, candidates=None, reason=""):
        self.status = status
        self.message = message
        # The lookup string (lower-cased) that matched the knowledge name;
        # None unless SELECTED.
        self.matched_term = matched_term
        # The stored knowledge row, exactly as the KnowledgeSystem returned
        # it (a deep copy); None unless SELECTED.
        self.record = record
        # `KnowledgeSystem.relationships_for(name)` for that entry, exactly
        # as returned (a deep copy); None unless SELECTED.
        self.relationships = relationships
        # AMBIGUOUS only: the names of the competing entries, sorted.
        self.candidates = list(candidates) if candidates else []
        self.reason = reason

    @property
    def selected(self):
        return self.status == STATUS_SELECTED

    def __repr__(self):
        return f"LearnedKnowledgeSelection(status={self.status!r})"

    def to_dict(self):
        """A fresh deep copy every call."""
        return copy.deepcopy({
            "status": self.status,
            "message": self.message,
            "matched_term": self.matched_term,
            "record": self.record,
            "relationships": self.relationships,
            "candidates": self.candidates,
            "reason": self.reason,
        })

    def to_context(self):
        """The `learned_knowledge_context` dict that response generation
        receives: `to_dict()` when SELECTED, else None (nothing is
        attached - the existing path stays exactly as it was)."""
        return self.to_dict() if self.selected else None


def _lookup_names(message, candidate_terms):
    """The exact names to look up, in a fixed order, without duplicates:
    the caller's candidate terms, then consecutive-word phrases."""
    names = []
    seen = set()

    def add(name):
        name = name.strip().lower()
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    for term in candidate_terms or ():
        if isinstance(term, str):
            add(term)
    words = [m.group().lower() for m in _WORD_RE.finditer(message)][:MAX_MESSAGE_WORDS]
    for size in range(2, MAX_PHRASE_WORDS + 1):
        for start in range(len(words) - size + 1):
            add(" ".join(words[start:start + size]))
    return names


def _original_casing(message):
    """{lower-cased phrase: the phrase as first written in `message`} for
    every word / consecutive-word run `_lookup_names` can produce, so a
    lookup can use the user's own casing (exact-case match wins)."""
    words = [m.group() for m in _WORD_RE.finditer(message)][:MAX_MESSAGE_WORDS]
    cased = {}
    for size in range(1, MAX_PHRASE_WORDS + 1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start:start + size])
            cased.setdefault(phrase.lower(), phrase)
    return cased


def _resolve(knowledge, lookup):
    """(record, ambiguous_names) for one lookup string. The existing
    `find_by_name_case_insensitive` stays the lookup (exact-case wins, a
    single case-insensitive match resolves - Prompt 637); only when it
    finds nothing is `resolve_name` consulted, purely to tell "unknown"
    from "several case-only duplicates" so the latter is never treated as
    if one of them had been chosen."""
    record = knowledge.find_by_name_case_insensitive(lookup)
    if record:
        return record, []
    resolver = getattr(knowledge, "resolve_name", None)
    if resolver is None:
        return None, []
    resolution = resolver(lookup)
    if resolution.get("status") == "ambiguous":
        return None, list(resolution.get("candidates") or [])
    return None, []


# Prompt 664: the one explicit "not for current use" lifecycle state written by
# KnowledgeSystem.set_status (Prompt 663). Retrieval APIs still expose such rows; this
# module selects knowledge for CURRENT assistance, so it does not.
INACTIVE_STATUS = "inactive"


def _is_inactive(record):
    return isinstance(record, dict) and record.get("status") == INACTIVE_STATUS


def _has_content(record, relationships):
    description = record.get("description")
    if isinstance(description, str) and description.strip():
        return True
    if isinstance(relationships, dict):
        return bool(relationships.get("outgoing") or relationships.get("incoming"))
    return False


def _current_relationships(knowledge, name):
    """Prompt 670: the relationship rows exposed in the context are CURRENT-only - rows whose other
    endpoint is inactive are dropped (KnowledgeSystem.current_relationships_for, Prompt 668), because this
    context is handed to response generation as current knowledge and to the reliability gate as evidence.
    Stored rows and raw relationships_for() are untouched; falls back to the raw read for a knowledge
    object without the helper (test doubles)."""
    fn = getattr(knowledge, "current_relationships_for", None)
    return fn(name) if callable(fn) else knowledge.relationships_for(name)


def select_learned_knowledge(message, knowledge, candidate_terms=None):
    """The `LearnedKnowledgeSelection` for `message` over `knowledge` (an
    existing `KnowledgeSystem`; only `find_by_name_case_insensitive` and
    `relationships_for` are called, both read-only).

    `candidate_terms` - the message's candidate terms from the existing
    term extraction (`understanding.term_extraction.extract_candidate_
    terms`); never computed here so this package keeps depending on no
    other project package. Omitted, only multi-word phrases of the message
    are tried.

    Never raises: a message that is not text is NOT_FOUND, a missing or
    failing knowledge system is FAILED."""
    if not isinstance(message, str) or not message.strip():
        return LearnedKnowledgeSelection(
            STATUS_NOT_FOUND, message=message if isinstance(message, str) else None,
            reason="no message text to match against")
    if knowledge is None:
        return LearnedKnowledgeSelection(
            STATUS_FAILED, message=message, reason="no knowledge system available")
    try:
        found = {}  # exact stored name -> (matched_term, record)
        ambiguous = set()  # stored names of unresolvable case-only duplicates
        cased = _original_casing(message)
        for name in _lookup_names(message, candidate_terms):
            record, competing = _resolve(knowledge, cased.get(name, name))
            if competing:
                ambiguous.update(competing)
            elif record and record.get("name") not in found:
                found[record["name"]] = (name, record)
        usable = {}
        for stored_name, (term, record) in found.items():
            relationships = _current_relationships(knowledge, stored_name)
            if not _is_inactive(record) and _has_content(record, relationships):
                usable[stored_name] = (term, copy.deepcopy(record),
                                       copy.deepcopy(relationships))
        # Case-only duplicates only count when they carry learned content.
        competing_usable = set()
        for stored_name in ambiguous:
            record = knowledge.get(stored_name)
            if (record and not _is_inactive(record)
                    and _has_content(record, _current_relationships(knowledge, stored_name))):
                competing_usable.add(stored_name)
    except Exception as exc:  # noqa: BLE001 - retrieval failure is a status, never an error
        return LearnedKnowledgeSelection(
            STATUS_FAILED, message=message, reason=f"knowledge retrieval failed: {exc}")

    if not usable and not competing_usable:
        return LearnedKnowledgeSelection(
            STATUS_NOT_FOUND, message=message, reason="no directly relevant learned knowledge")
    if len(usable) > 1 or competing_usable:
        return LearnedKnowledgeSelection(
            STATUS_AMBIGUOUS, message=message, candidates=sorted(set(usable) | competing_usable),
            reason="more than one learned knowledge entry is directly relevant")
    (term, record, relationships), = usable.values()
    return LearnedKnowledgeSelection(
        STATUS_SELECTED, message=message, matched_term=term, record=record,
        relationships=relationships, reason="exactly one directly relevant learned knowledge entry")
