"""
Language Intelligence - Language Learning Store
====================================================
Prompt 416. A small, structured foundation for recording and retrieving
learned language items - words, phrases, and sentence patterns - one
language/locale at a time, so a *future* learning module can teach the
system a language without this file (or anything above it) needing to
change.

This is NOT a natural-language learner and NOT a hand-built dictionary:
nothing here invents a meaning, a translation, an example, or a
relationship. It only stores what a caller explicitly gives it and
returns it back unchanged - the exact same "structure, don't fabricate"
posture the rest of language_intelligence/ already takes (see this
package's own __init__.py).

Reuse map (this stage adds no new storage engine and no new intelligence):

    storage         MemorySystem (memory/memory_system.py) - one more
                    table, `language_learning_items` (schema migration
                    5), added the exact same purely-additive way every
                    other structured table (knowledge, skills, rules,
                    ...) already was. This is NOT a second, parallel
                    memory system - every read/write here goes through
                    the one MemorySystem instance a caller supplies,
                    via its existing `query` / `query_one` / `_run`
                    helpers, same as KnowledgeSystem does.
    language/locale `language_context.canonical_language` (Prompt 401) -
                    the SAME normalization LanguageContext already
                    applies, so an item recorded under "fa" and one
                    recorded under "persian" are the same entry. No
                    second, competing language table or vocabulary is
                    introduced; an unrecognized code/name is kept
                    exactly as `canonical_language` already handles it
                    for the rest of this package (passed through,
                    lowercased) - so this store is language-agnostic by
                    construction, not by a list of "supported"
                    languages hard-coded here.
    identity/update deterministic key match ONLY: (language, item_type,
                    a case-folded/whitespace-collapsed form of the key).
                    The same "look up first, then UPDATE or INSERT,
                    preserve what the caller doesn't overwrite" shape
                    `knowledge.knowledge_system.KnowledgeSystem.learn`/
                    `.relate` already use - reused here rather than a
                    second matching strategy. No fuzzy matching, no
                    embeddings: same word/phrase text always resolves
                    to the same row.
    episodic history `MemorySystem.add_learning_event` (the same table
                    LearningSystem.teach()/relate() already write to)
                    records every learn_item() call - reused, not
                    duplicated with a second history table.
    integration     Core (core/core.py) owns one LanguageLearningStore
                    instance, exactly like it owns self.knowledge /
                    self.concepts / self.learning, via two thin
                    passthrough methods (learn_language_item /
                    get_language_item). LanguageIntelligenceCore,
                    LocalLanguageModelBackend, LocalModelRuntime,
                    ConversationContext, the Knowledge System's own
                    tables, and the Agent Loop are none of them touched
                    or redesigned by this stage - this is an entirely
                    separate table and a separate, small, composed
                    class, reached only through Core's own new methods.

What one learned item carries (see LanguageLearningItem.to_dict()):

    language        canonicalized via `canonical_language()`; required
                    (a placeholder like "" / "unknown" is rejected - a
                    language item without a language/locale is not a
                    valid item for this store to associate anything
                    with).
    item_type       a short, caller-chosen, non-empty label. The
                    ITEM_TYPE_* constants below (word / phrase /
                    pattern) are offered purely as a convenience default
                    vocabulary - they are NOT enforced. A future
                    learning module is free to use its own item_type
                    strings (e.g. "affix", "idiom") without this module
                    changing at all.
    key             the learned text, verbatim - a word, a phrase, or a
                    sentence-pattern template (e.g. "___ is a ___").
                    Never normalized, translated, or rewritten.
    meaning         an arbitrary, caller-shaped JSON-safe value (a
                    gloss, a translation map, semantic roles, ...) -
                    this module never interprets or validates its
                    internal shape, only that it is JSON-serializable.
    relationships   a list of small, caller-shaped dicts describing a
                    grammatical or semantic link to another item (e.g.
                    {"type": "synonym_of", "target": "happy"}).
                    `type` is a freeform string on purpose: no relation
                    vocabulary for any language is fixed here.
    examples        a list of example strings (usage in context).
    confidence      a float in [0.0, 1.0]. On an update, None means
                    "leave the stored value alone" - exactly
                    `KnowledgeSystem.learn()`'s own confidence policy -
                    and a new item with no confidence given defaults to
                    1.0, also matching that policy.
    source          a short label for who/what taught this item (e.g.
                    "user", "conversation", "ael") - plays the same role
                    as `knowledge.source`.
    source_context  the sentence/text/conversation excerpt this item was
                    learned from - plays the same role as
                    `knowledge.source_text`.
    learning_method how it was learned (e.g. "manual", "conversation") -
                    plays the same role as `knowledge.learning_method`.
    version/timestamps  `version` increments on every successful
                    learn_item() call against an existing row (never on
                    the first INSERT, which starts at 1) - same
                    "version-bump on update" convention `knowledge`
                    already follows.

On an update, `meaning` / `examples` / `relationships` follow the same
"None means leave the stored value alone, anything else replaces it
outright" rule as `confidence`/`source`/`source_context`/
`learning_method` - there is no implicit merging of two example lists
or two relationship lists. A caller that wants to add one example to
an existing item passes the full, updated list.
"""

import contextlib
import json
from datetime import datetime, timezone

from .language_context import canonical_language


def _now():
    return datetime.now(timezone.utc).isoformat()



ITEM_TYPE_WORD = "word"
ITEM_TYPE_PHRASE = "phrase"
ITEM_TYPE_PATTERN = "pattern"

# Offered as a convenience default vocabulary only - see the module
# docstring's `item_type` entry. learn_item()/get_item() accept ANY
# non-empty string here, not just these three.
SUGGESTED_ITEM_TYPES = (ITEM_TYPE_WORD, ITEM_TYPE_PHRASE, ITEM_TYPE_PATTERN)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _resolve_language(language):
    """Canonicalize `language` the same way `language_context.py`
    already does (Prompt 401). Raises ValueError for anything that
    names no real language/locale (None, "", "unknown", ...) - a
    language item must be associated with an actual language."""
    _require_text(language, "language")
    canonical = canonical_language(language)
    if canonical is None:
        raise ValueError(f"language {language!r} does not name a language/locale")
    return canonical


def _normalize_key(key):
    """Case-folded, whitespace-collapsed form of `key`, used only for
    identity matching (never stored as the display text, never shown to
    a caller). `casefold()` is a safe no-op on scripts with no case
    (Persian, Arabic, ...), so this stays language-agnostic."""
    return " ".join(key.strip().split()).casefold()


def _clamp_confidence(confidence):
    """None passes through unchanged (the "leave it alone / use the
    default" sentinel - see the module docstring). Any given value must
    be a real number; it is clamped into [0.0, 1.0], the same safety
    margin `DeterministicFallbackBackend._score_confidence` already
    applies elsewhere in this package."""
    if confidence is None:
        return None
    if not _is_number(confidence):
        raise TypeError("confidence must be a number or None")
    return max(0.0, min(1.0, float(confidence)))


def _json_or_default(text, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


class LanguageLearningItem:
    """Plain, JSON-shaped record - same `to_dict()` convention used
    throughout this project. Never constructed directly by a caller;
    `LanguageLearningStore.learn_item()` / `.get_item()` return these
    from what is actually stored."""

    def __init__(self, item_id, language, item_type, key, meaning, examples,
                 relationships, confidence, source, source_context, learning_method,
                 version, created_at, updated_at):
        self.item_id = item_id
        self.language = language
        self.item_type = item_type
        self.key = key
        self.meaning = meaning
        self.examples = examples
        self.relationships = relationships
        self.confidence = confidence
        self.source = source
        self.source_context = source_context
        self.learning_method = learning_method
        self.version = version
        self.created_at = created_at
        self.updated_at = updated_at

    def __repr__(self):
        return (
            f"LanguageLearningItem(language={self.language!r}, item_type={self.item_type!r}, "
            f"key={self.key!r}, confidence={self.confidence!r}, version={self.version!r})"
        )

    def to_dict(self):
        return {
            "id": self.item_id,
            "language": self.language,
            "item_type": self.item_type,
            "key": self.key,
            "meaning": self.meaning,
            "examples": list(self.examples),
            "relationships": list(self.relationships),
            "confidence": self.confidence,
            "source": self.source,
            "source_context": self.source_context,
            "learning_method": self.learning_method,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        return cls(
            item_id=row["id"], language=row["language"], item_type=row["item_type"],
            key=row["item_key"],
            meaning=_json_or_default(row["meaning"], {}),
            examples=_json_or_default(row["examples"], []),
            relationships=_json_or_default(row["relationships"], []),
            confidence=row["confidence"], source=row["source"],
            source_context=row["source_context"], learning_method=row["learning_method"],
            version=row["version"], created_at=row["created_at"], updated_at=row["updated_at"],
        )


class LanguageLearningStore:
    """Composes an existing `MemorySystem` (memory/memory_system.py) -
    never constructs or owns its own storage. One instance is safe to
    share the way Core shares one `KnowledgeSystem` - every method is a
    single, deterministic read or write against the
    `language_learning_items` table (schema migration 5)."""

    def __init__(self, memory):
        self.memory = memory

    def _atomic(self):
        """Prompt 646: the store's Prompt 645 atomic scope if it has one
        (a real MemorySystem), else a no-op context (memory=None / fakes)."""
        fn = getattr(type(self.memory), "_atomic", None)
        return fn(self.memory) if callable(fn) else contextlib.nullcontext()

    # ------------------------------------------------------------------
    def learn_item(self, language, item_type, key, meaning=None, examples=None,
                    relationships=None, confidence=None, source=None, source_context=None,
                    learning_method=None):
        """Record a new learned language item, or update the existing one
        that matches (language, item_type, a normalized form of key).

        Deterministic: the same (language, item_type, key) triple always
        resolves to the same row - see `_normalize_key` - so re-teaching
        it never creates a duplicate. `meaning`/`examples`/`relationships`
        left as None on an update leave the stored value untouched (see
        the module docstring); given explicitly, they replace it outright.
        `confidence`/`source`/`source_context`/`learning_method` follow
        the identical None-means-leave-alone rule.

        Returns the resulting item as a dict (see
        `LanguageLearningItem.to_dict()`)."""
        language = _resolve_language(language)
        item_type = _require_text(item_type, "item_type")
        key = _require_text(key, "key")
        normalized_key = _normalize_key(key)
        confidence = _clamp_confidence(confidence)

        # Prompt 646: the row write and its learning event commit together.
        with self._atomic():
            existing = self._find_row(language, item_type, normalized_key)
            now = _now()
            if existing:
                self._update_row(
                    existing, key=key, meaning=meaning, examples=examples,
                    relationships=relationships, confidence=confidence, source=source,
                    source_context=source_context, learning_method=learning_method, now=now,
                )
                event_type = "language_item_updated"
            else:
                self._insert_row(
                    language=language, item_type=item_type, key=key, normalized_key=normalized_key,
                    meaning=meaning, examples=examples, relationships=relationships,
                    confidence=confidence, source=source, source_context=source_context,
                    learning_method=learning_method, now=now,
                )
                event_type = "language_item_learned"

            if self.memory is not None:
                self.memory.add_learning_event(
                    event_type, f"{language}:{item_type}:{key}",
                    detail=source_context,
                    # Prompt 647: log the PERSISTED source (None argument keeps the stored one).
                    source=existing["source"] if (existing and source is None) else source,
                )
        return self.get_item(language, item_type, key)

    def get_item(self, language, item_type, key):
        """Retrieve a previously learned item as a dict, or None if no
        item matches (language, item_type, a normalized form of key).
        Read-only: never creates, updates, or deletes anything."""
        language = _resolve_language(language)
        item_type = _require_text(item_type, "item_type")
        key = _require_text(key, "key")
        row = self._find_row(language, item_type, _normalize_key(key))
        item = LanguageLearningItem.from_row(row)
        return item.to_dict() if item is not None else None

    def find_items(self, key, language=None, item_type=None, limit=None):
        """Every learned item whose key matches `key` (the same
        case/whitespace-insensitive identity `get_item()` uses), as a list
        of dicts - for callers that have an expression but do not know
        its `item_type` (Prompt 418, meaning resolution).

        `language` and `item_type` each narrow the match when given; with
        no `language`, items of every language that share the written
        form are returned - never merged, each carries its own language.
        Ordered by (language, item_type, id), so the result never depends
        on insertion order. `limit` (a non-negative int) caps how many
        rows are read. Read-only: never creates, updates or deletes."""
        key = _require_text(key, "key")
        sql = "SELECT * FROM language_learning_items WHERE normalized_key = ?"
        params = [_normalize_key(key)]
        if language is not None:
            sql += " AND language = ?"
            params.append(_resolve_language(language))
        if item_type is not None:
            sql += " AND item_type = ?"
            params.append(_require_text(item_type, "item_type"))
        sql += " ORDER BY language, item_type, id"
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool):
                raise TypeError("limit must be an int or None")
            if limit < 0:
                raise ValueError("limit must not be negative")
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.memory.query(sql, tuple(params))
        return [LanguageLearningItem.from_row(row).to_dict() for row in rows]

    def items_for_language(self, language, item_type=None):
        """All items recorded for `language` (optionally narrowed to one
        `item_type`), as a list of dicts, ordered by item_key. Read-only."""
        language = _resolve_language(language)
        if item_type is not None:
            item_type = _require_text(item_type, "item_type")
            rows = self.memory.query(
                "SELECT * FROM language_learning_items WHERE language = ? AND item_type = ? "
                "ORDER BY item_key",
                (language, item_type),
            )
        else:
            rows = self.memory.query(
                "SELECT * FROM language_learning_items WHERE language = ? ORDER BY item_key",
                (language,),
            )
        return [LanguageLearningItem.from_row(row).to_dict() for row in rows]

    def languages(self):
        """The distinct languages/locales with at least one learned item
        (canonicalized identifiers, sorted). Read-only."""
        rows = self.memory.query(
            "SELECT DISTINCT language FROM language_learning_items ORDER BY language"
        )
        return [row["language"] for row in rows]

    # ------------------------------------------------------------------
    def _find_row(self, language, item_type, normalized_key):
        return self.memory.query_one(
            "SELECT * FROM language_learning_items WHERE language = ? AND item_type = ? "
            "AND normalized_key = ?",
            (language, item_type, normalized_key),
        )

    def _insert_row(self, language, item_type, key, normalized_key, meaning, examples,
                     relationships, confidence, source, source_context, learning_method, now):
        self.memory._run(
            "INSERT INTO language_learning_items (language, item_type, item_key, normalized_key, "
            "meaning, examples, relationships, confidence, source, source_context, "
            "learning_method, version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                language, item_type, key, normalized_key,
                json.dumps(meaning if meaning is not None else {}),
                json.dumps(list(examples) if examples else []),
                json.dumps(list(relationships) if relationships else []),
                1.0 if confidence is None else confidence,
                source, source_context, learning_method, now, now,
            ),
        )

    def _update_row(self, existing, key, meaning, examples, relationships, confidence,
                     source, source_context, learning_method, now):
        new_meaning = existing["meaning"] if meaning is None else json.dumps(meaning)
        new_examples = existing["examples"] if examples is None else json.dumps(list(examples))
        new_relationships = (
            existing["relationships"] if relationships is None else json.dumps(list(relationships))
        )
        new_confidence = existing["confidence"] if confidence is None else confidence
        new_source = existing["source"] if source is None else source
        new_source_context = (
            existing["source_context"] if source_context is None else source_context
        )
        new_learning_method = (
            existing["learning_method"] if learning_method is None else learning_method
        )
        self.memory._run(
            "UPDATE language_learning_items SET item_key = ?, meaning = ?, examples = ?, "
            "relationships = ?, confidence = ?, source = ?, source_context = ?, "
            "learning_method = ?, version = version + 1, updated_at = ? WHERE id = ?",
            (
                key, new_meaning, new_examples, new_relationships, new_confidence, new_source,
                new_source_context, new_learning_method, now, existing["id"],
            ),
        )
