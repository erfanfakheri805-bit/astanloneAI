"""
Language Intelligence - Learned Language Relationships
====================================================
Prompt 417. A small, structured way to connect learned language items
(Prompt 416: words, phrases, sentence patterns, or any caller-defined
item_type) to each other - and, optionally, to a Knowledge System concept
- so a *future* learning module can record "these two things are related,
and this is how" without this file needing to change.

Like the rest of this package (and Prompt 416 before it) this is
"structure, don't fabricate": nothing here invents a synonym, a
translation, an example or a grammatical relation. It stores exactly the
links a caller explicitly gives it, and returns them unchanged.

Reuse map (this stage adds no new intelligence and no second database):

    items           LanguageLearningStore (Prompt 416) - every endpoint is
                    resolved through its public `get_item()`, using the
                    same (language, item_type, key) identity, the same
                    `canonical_language()` normalization ("fa" ==
                    "persian") and the same case/whitespace-insensitive
                    key matching. Nothing is looked up a second way.
    concepts        KnowledgeSystem (knowledge/knowledge_system.py) - a
                    concept endpoint must be an existing knowledge entry
                    of kind 'concept', exactly what ConceptSystem defines
                    a concept to be. This module never creates, edits or
                    relates a knowledge entry, and never writes to the
                    Knowledge System's own `relationships` table.
    storage         MemorySystem (memory/memory_system.py) - one more
                    table, `language_item_relationships` (schema
                    migration 6), on the same SQLite connection.
    history         `MemorySystem.add_learning_event`, the same episodic
                    table LanguageLearningStore.learn_item() already
                    writes to - not a second history table.
    integration     Core owns one instance (`self.language_relationships`)
                    via two thin passthrough methods
                    (relate_language_items / get_language_relationships),
                    next to the Prompt 416 ones. The Local Language Model
                    runtime, backend selection/fallback, the Knowledge /
                    Concept / Learning systems and the Agent Loop are not
                    touched.

Why not simply reuse `KnowledgeSystem.relate()` / the existing
`relationships` table? That table's foreign keys point only at
`knowledge(name)`, so it cannot reference a learned language item, and
`relate()` auto-creates stub knowledge entries for names it has never seen
- the opposite of what a link between *actual* learned items must do.
Mirroring every language item into `knowledge` instead would put
thousands of words into concept counts and conversational knowledge
search. So this table mirrors the *shape* of `relationships` (same
provenance columns, same idempotent "look up, refresh metadata, never
duplicate" behaviour) while pointing at the right things.

What one relationship carries (see LanguageRelationshipStore._to_dict()):

    from / to       the two endpoints. An endpoint is either
                        {"kind": "item", "id", "language", "item_type",
                         "key"}                  - a learned language item
                        {"kind": "concept", "concept": name,
                         "language": None}       - a Knowledge concept
                    Nothing assumes "word -> word": phrase -> meaning,
                    word -> phrase, phrase -> sentence pattern,
                    expression -> concept and concept -> expression are
                    all just endpoint pairs (a "meaning" can be learned
                    as an item of item_type "meaning").
    relation_type   a short, caller-chosen, non-empty label, stored as
                    given. The RELATION_* constants below are offered as
                    a convenience vocabulary only - like Prompt 416's
                    ITEM_TYPE_* they are NOT enforced; any string works.
    symmetric       True when the two ends are interchangeable (a
                    synonym of b == b synonym of a). Such a relationship
                    is stored ONCE, in a canonical endpoint order, so
                    relating (a, b) and then (b, a) never makes a second
                    row; it is retrievable from either side. Defaults to
                    a suggestion per relation type (SYMMETRIC_BY_DEFAULT)
                    and can always be stated explicitly; an unknown type
                    defaults to directed.
    metadata        an arbitrary, caller-shaped JSON-safe value - never
                    interpreted here.
    confidence, source, source_context, learning_method
                    provenance, with the same policy as the Prompt 416
                    items / `KnowledgeSystem`: on a repeat, None means
                    "leave what is stored alone"; a new relationship with
                    no confidence defaults to 1.0; confidence is clamped
                    into [0.0, 1.0].
    version / timestamps
                    `version` starts at 1 and increments each time the
                    same relationship is stated again (which also
                    refreshes `updated_at`; `created_at` never moves).

Endpoints are given as small dicts: `item_ref(language, item_type, key)`
(or any dict with those three keys - including an item returned by
`LanguageLearningStore.learn_item()` / `.get_item()`) and
`concept_ref(name)`. An endpoint that does not exist is rejected with
ValueError; it is never auto-created. The database itself also refuses a
dangling reference (real foreign keys, see memory_system._migration_6).

Duplicates: the identity of a relationship is (from endpoint, to endpoint,
normalized relation_type) - or, for a symmetric one, the unordered pair.
Stating it again refreshes the row (never inserts a second one). The same
pair and type restated with the opposite `symmetric` value is refused,
because silently flipping a relationship's meaning would be worse than an
error.

Language filtering: a relationship may cross languages (an English word
and its Persian translation). `relationships_for(..., language=...)` keeps
only relationships whose OTHER end is in that language, and
`relationships_in_language()` lists every relationship with an end in a
language. Language names are canonicalized like everywhere else; a concept
has no language, so it never matches a language filter.

Results are ordered deterministically (relation type, then endpoint
language and key) - never by storage accident.
"""

import json
from collections import namedtuple

from knowledge.knowledge_system import KnowledgeSystem

from .language_learning_store import (
    LanguageLearningStore,
    _clamp_confidence,
    _json_or_default,
    _normalize_key,
    _now,
    _require_text,
    _resolve_language,
)


RELATION_SYNONYM = "synonym"
RELATION_ANTONYM = "antonym"
RELATION_TRANSLATION = "translation"
RELATION_RELATED_MEANING = "related_meaning"
RELATION_EXAMPLE_USAGE = "example_usage"
RELATION_GRAMMATICAL = "grammatical_relation"
RELATION_WORD_TO_PHRASE = "word_to_phrase"
RELATION_PHRASE_TO_PATTERN = "phrase_to_pattern"
RELATION_CONCEPT_TO_EXPRESSION = "concept_to_expression"

# Offered as a convenience default vocabulary only - see the module
# docstring's `relation_type` entry. relate() accepts ANY non-empty string.
SUGGESTED_RELATION_TYPES = (
    RELATION_SYNONYM, RELATION_ANTONYM, RELATION_TRANSLATION, RELATION_RELATED_MEANING,
    RELATION_EXAMPLE_USAGE, RELATION_GRAMMATICAL, RELATION_WORD_TO_PHRASE,
    RELATION_PHRASE_TO_PATTERN, RELATION_CONCEPT_TO_EXPRESSION,
)

# Suggested default for `symmetric` when a caller does not state it: the
# suggested types whose two ends are interchangeable. Only a default -
# `symmetric=True/False` always wins, and any other relation type is
# directed unless the caller says otherwise.
SYMMETRIC_BY_DEFAULT = frozenset({
    RELATION_SYNONYM, RELATION_ANTONYM, RELATION_TRANSLATION, RELATION_RELATED_MEANING,
})

KIND_ITEM = "item"
KIND_CONCEPT = "concept"

_CONCEPT_KIND = "concept"  # knowledge.kind of a concept (see ConceptSystem)

# One resolved, existing endpoint. `label` is only used for history text.
_Endpoint = namedtuple("_Endpoint", ["kind", "item_id", "concept", "label"])


def item_ref(language, item_type, key):
    """Reference a learned language item (Prompt 416) by its identity."""
    return {"language": language, "item_type": item_type, "key": key}


def concept_ref(name):
    """Reference a Knowledge System concept by name."""
    return {"concept": name}


def _sort_key(endpoint):
    """Canonical order for the two ends of a symmetric relationship."""
    if endpoint.kind == KIND_ITEM:
        return (0, endpoint.item_id, "")
    return (1, 0, endpoint.concept)


_SELECT = (
    "SELECT r.*, "
    "fi.language AS from_language, fi.item_type AS from_item_type, fi.item_key AS from_key, "
    "ti.language AS to_language, ti.item_type AS to_item_type, ti.item_key AS to_key "
    "FROM language_item_relationships r "
    "LEFT JOIN language_learning_items fi ON fi.id = r.from_item_id "
    "LEFT JOIN language_learning_items ti ON ti.id = r.to_item_id "
)


def _endpoint_dict(row, side):
    item_id = row[f"{side}_item_id"]
    if item_id is not None:
        return {
            "kind": KIND_ITEM, "id": item_id, "language": row[f"{side}_language"],
            "item_type": row[f"{side}_item_type"], "key": row[f"{side}_key"],
        }
    return {"kind": KIND_CONCEPT, "concept": row[f"{side}_concept"], "language": None}


def _endpoint_order_text(endpoint_dict):
    return (endpoint_dict["language"] or "", endpoint_dict.get("key") or endpoint_dict.get("concept") or "")


class LanguageRelationshipStore:
    """Composes an existing `MemorySystem`, `LanguageLearningStore` and
    `KnowledgeSystem` - never constructs or owns storage of its own. Every
    method is a deterministic read or write against the
    `language_item_relationships` table (schema migration 6)."""

    def __init__(self, memory, language_learning=None, knowledge=None):
        self.memory = memory
        self.language_learning = (
            language_learning if language_learning is not None else LanguageLearningStore(memory)
        )
        self.knowledge = knowledge if knowledge is not None else KnowledgeSystem(memory)

    # ------------------------------------------------------------------
    def relate(self, from_ref, to_ref, relation_type, symmetric=None, metadata=None,
               confidence=None, source=None, source_context=None, learning_method=None):
        """Record a relationship between two existing learned items (or
        an item and an existing concept), or refresh the one that already
        exists. See the module docstring for endpoints, symmetry and the
        duplicate rule.

        Raises ValueError if either endpoint does not exist (nothing is
        auto-created), if both ends are the same, or if the relationship
        already exists with the opposite `symmetric` value.

        Returns the relationship as a dict (see `_to_dict`), plus a
        `created` flag: True if this call created it, False if it was
        already known and was refreshed instead."""
        relation_type = _require_text(relation_type, "relation_type")
        normalized_type = _normalize_key(relation_type)
        confidence = _clamp_confidence(confidence)
        if symmetric is not None and not isinstance(symmetric, bool):
            raise TypeError("symmetric must be a bool or None")
        metadata_json = json.dumps(metadata) if metadata is not None else None

        # One lock span, so look-up-then-write cannot interleave with
        # another thread's relate() (MemorySystem's lock is re-entrant).
        # Prompt 646: the relationship write and its event commit together
        # (Prompt 645 _atomic scope; it holds the same re-entrant lock).
        with self.memory._lock, self.memory._atomic():
            first = self._require_endpoint(from_ref, "from_ref")
            second = self._require_endpoint(to_ref, "to_ref")
            if first == second:
                raise ValueError("a language item cannot be related to itself")
            if symmetric is None:
                symmetric = normalized_type in SYMMETRIC_BY_DEFAULT
            if symmetric and _sort_key(second) < _sort_key(first):
                first, second = second, first

            existing = self._find_existing(first, second, normalized_type, symmetric)
            now = _now()
            if existing is not None:
                if bool(existing["symmetric"]) != symmetric:
                    raise ValueError(
                        f"this relationship already exists with symmetric="
                        f"{bool(existing['symmetric'])}; it cannot be restated with "
                        f"symmetric={symmetric}"
                    )
                self._update_row(
                    existing, relation_type, metadata_json, confidence, source,
                    source_context, learning_method, now,
                )
                relationship_id, created = existing["id"], False
                event_type = "language_relationship_updated"
            else:
                relationship_id = self._insert_row(
                    first, second, relation_type, normalized_type, symmetric, metadata_json,
                    confidence, source, source_context, learning_method, now,
                )
                created = True
                event_type = "language_relationship_learned"

            arrow = "<->" if symmetric else "->"
            self.memory.add_learning_event(
                event_type, f"{first.label} -[{relation_type}]{arrow} {second.label}",
                detail=source_context,
                # Prompt 647: log the PERSISTED source (None argument keeps the stored one).
                source=existing["source"] if (existing is not None and source is None) else source,
            )
            result = self._to_dict(self._select("WHERE r.id = ?", (relationship_id,))[0])
        result["created"] = created
        return result

    def relationships_for(self, ref, relation_type=None, language=None):
        """Every relationship touching `ref` (a learned item or a
        concept), from either side, as a list of dicts - each one a
        relationship dict (see `_to_dict`) plus:

            direction   "outgoing" (ref is the `from` end), "incoming"
                        (ref is the `to` end) or "both" (a symmetric
                        relationship, where the ends are interchangeable)
            related     the OTHER endpoint, whichever side it was stored on

        `relation_type` (case/whitespace-insensitive) narrows to one
        type; `language` narrows to relationships whose OTHER end is a
        learned item in that language/locale. An endpoint that does not
        exist yields []. Read-only."""
        endpoint = self._lookup_endpoint(ref)
        if language is not None:
            language = _resolve_language(language)
        if endpoint is None:
            return []

        if endpoint.kind == KIND_ITEM:
            where, params = "WHERE (r.from_item_id = ? OR r.to_item_id = ?)", [endpoint.item_id] * 2
        else:
            where, params = "WHERE (r.from_concept = ? OR r.to_concept = ?)", [endpoint.concept] * 2
        if relation_type is not None:
            where += " AND r.normalized_type = ?"
            params.append(_normalize_key(_require_text(relation_type, "relation_type")))

        results = []
        for row in self._select(where, tuple(params)):
            relationship = self._to_dict(row)
            is_from = (
                row["from_item_id"] == endpoint.item_id if endpoint.kind == KIND_ITEM
                else row["from_concept"] == endpoint.concept
            )
            related = relationship["to"] if is_from else relationship["from"]
            if language is not None and related["language"] != language:
                continue
            relationship["direction"] = (
                "both" if relationship["symmetric"] else ("outgoing" if is_from else "incoming")
            )
            relationship["related"] = related
            results.append((row["normalized_type"], _endpoint_order_text(related), row["id"], relationship))
        results.sort(key=lambda entry: entry[:3])
        return [entry[3] for entry in results]

    def relationships_in_language(self, language, relation_type=None):
        """Every relationship with at least one end that is a learned
        item in `language` (a relationship between an English and a
        Persian item appears under both), as a list of relationship dicts.
        Optionally narrowed to one `relation_type`. Read-only."""
        language = _resolve_language(language)
        where, params = "WHERE (fi.language = ? OR ti.language = ?)", [language, language]
        if relation_type is not None:
            where += " AND r.normalized_type = ?"
            params.append(_normalize_key(_require_text(relation_type, "relation_type")))
        rows = self._select(where, tuple(params))
        rows.sort(key=lambda row: (
            row["normalized_type"], _endpoint_order_text(_endpoint_dict(row, "from")),
            _endpoint_order_text(_endpoint_dict(row, "to")), row["id"],
        ))
        return [self._to_dict(row) for row in rows]

    # ------------------------------------------------------------------
    def _lookup_endpoint(self, ref):
        """The existing endpoint `ref` names, or None if it does not
        exist. Raises for a malformed `ref`. Read-only."""
        if not isinstance(ref, dict):
            raise TypeError("an endpoint must be a dict - see item_ref() / concept_ref()")
        if "concept" in ref:
            name = _require_text(ref["concept"], "concept")
            row = self.knowledge.get(name)
            if row is None or row["kind"] != _CONCEPT_KIND:
                return None
            return _Endpoint(KIND_CONCEPT, None, name, f"concept:{name}")
        item = self.language_learning.get_item(
            ref.get("language"), ref.get("item_type"), ref.get("key")
        )
        if item is None:
            return None
        return _Endpoint(
            KIND_ITEM, item["id"], None, f"{item['language']}:{item['item_type']}:{item['key']}"
        )

    def _require_endpoint(self, ref, role):
        endpoint = self._lookup_endpoint(ref)
        if endpoint is None:
            raise ValueError(
                f"{role} does not refer to an existing learned language item or concept "
                f"({ref!r}); learn it first - relationships never create their own endpoints"
            )
        return endpoint

    def _row_between(self, first, second, normalized_type):
        return self.memory.query_one(
            "SELECT * FROM language_item_relationships WHERE normalized_type = ? "
            "AND from_item_id IS ? AND from_concept IS ? AND to_item_id IS ? AND to_concept IS ?",
            (normalized_type, first.item_id, first.concept, second.item_id, second.concept),
        )

    def _find_existing(self, first, second, normalized_type, symmetric):
        forward = self._row_between(first, second, normalized_type)
        if forward is not None:
            return forward
        reverse = self._row_between(second, first, normalized_type)
        if reverse is not None and (symmetric or reverse["symmetric"]):
            return reverse
        return None

    def _insert_row(self, first, second, relation_type, normalized_type, symmetric,
                    metadata_json, confidence, source, source_context, learning_method, now):
        cursor = self.memory._run(
            "INSERT INTO language_item_relationships (from_item_id, from_concept, to_item_id, "
            "to_concept, relation_type, normalized_type, symmetric, metadata, confidence, "
            "source, source_context, learning_method, version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                first.item_id, first.concept, second.item_id, second.concept, relation_type,
                normalized_type, 1 if symmetric else 0, metadata_json,
                1.0 if confidence is None else confidence, source, source_context,
                learning_method, now, now,
            ),
        )
        return cursor.lastrowid

    def _update_row(self, existing, relation_type, metadata_json, confidence, source,
                    source_context, learning_method, now):
        self.memory._run(
            "UPDATE language_item_relationships SET relation_type = ?, metadata = ?, "
            "confidence = ?, source = ?, source_context = ?, learning_method = ?, "
            "version = version + 1, updated_at = ? WHERE id = ?",
            (
                relation_type,
                existing["metadata"] if metadata_json is None else metadata_json,
                existing["confidence"] if confidence is None else confidence,
                existing["source"] if source is None else source,
                existing["source_context"] if source_context is None else source_context,
                existing["learning_method"] if learning_method is None else learning_method,
                now, existing["id"],
            ),
        )

    def _select(self, where, params):
        return self.memory.query(_SELECT + where, params)

    @staticmethod
    def _to_dict(row):
        """Plain, JSON-shaped relationship record - the same `to_dict()`
        convention used throughout this project."""
        return {
            "id": row["id"],
            "relation_type": row["relation_type"],
            "symmetric": bool(row["symmetric"]),
            "from": _endpoint_dict(row, "from"),
            "to": _endpoint_dict(row, "to"),
            "metadata": _json_or_default(row["metadata"], {}),
            "confidence": row["confidence"],
            "source": row["source"],
            "source_context": row["source_context"],
            "learning_method": row["learning_method"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
