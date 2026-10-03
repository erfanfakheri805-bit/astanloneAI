"""
Language Intelligence - Learned Meaning Resolution
====================================================
Prompt 418. Given a written expression - a learned word, phrase or
sentence pattern - report what the system has LEARNED it to mean, using
only the language items (Prompt 416) and relationships (Prompt 417) that
are already stored.

This is a lookup, not understanding. Nothing here parses a sentence,
infers a meaning, guesses a translation, matches fuzzily or consults a
model: an expression either has learned meaning information in the store
or it does not, and the result says which - the same "structure, don't
fabricate" posture as the rest of this package.

Reuse map (this stage adds no storage and no new knowledge):

    items           LanguageLearningStore (Prompt 416) - the expression is
                    matched with the SAME case/whitespace-insensitive key
                    identity and `canonical_language()` normalization
                    ("fa" == "persian"), through one small read-only
                    addition, `find_items()` (an expression rarely comes
                    with its item_type, so an exact-triple `get_item()`
                    is not enough).
    relationships   LanguageRelationshipStore (Prompt 417) - traversal
                    goes only through its public `relationships_for()`.
                    No relationship is read any other way, and none is
                    ever created or changed here.
    concepts        KnowledgeSystem (knowledge/knowledge_system.py) - when
                    a relationship reaches a concept, its stored
                    description/status are read from the existing
                    knowledge entry. Concepts are knowledge entries of
                    kind 'concept' (ConceptSystem's definition); nothing
                    is created, stubbed or edited.
    integration     Core owns one instance (`self.meaning_resolver`) via
                    one thin passthrough, `resolve_language_meaning`. The
                    Local Language Model runtime, backend
                    selection/fallback and the Agent Loop are untouched.
                    Resolution is READ-ONLY: it writes nothing, not even
                    a learning event.

Statuses (module constants, like every other result in this package).
The existing statuses elsewhere are domain-specific - response
generation's (`response_generation.STATUS_*`) describe producing text, and
the `NOT_FOUND` constants in self_upgrade/ describe stored upgrade
requests - so none of them is reused for "does the system know this
expression"; sharing them would couple the language layer to unrelated
systems.

    STATUS_RESOLVED    "RESOLVED"   at least one learned meaning was found
    STATUS_NOT_FOUND   "NOT_FOUND"  none was; `reason` says why:
        REASON_UNKNOWN_EXPRESSION   no learned item matches the expression
                                    (in that language / item_type)
        REASON_NO_LEARNED_MEANING   the expression IS a learned item, but
                                    nothing meaning-bearing is stored for
                                    it: an empty `meaning` and no
                                    relationships that could be followed

What counts as a learned meaning, for one matched item: its stored
`meaning` (any non-empty, caller-shaped JSON value - never interpreted
here), and/or at least one relationship reached by the bounded traversal
below. A translation link is meaning information even when the linked
item itself has no stored meaning.

Language awareness. The same written form in two languages is two items
with their own meanings and their own relationships, and is never merged.
`language` narrows to one language/locale. Left as None (language not
available), every language's item is returned, each entry carrying its own
`language` - so no expression is ever given one global meaning.

Several meanings. Each matching item is one entry in `meanings`, ordered
by (language, item_type) and never ranked or merged. The store's identity
is (language, item_type, key), so a word learned under two item_types in
one language (say "noun" and "verb") is two entries, each with its own
relationships; several concepts linked to one item are separate `related`
entries. `ambiguous` is True whenever there is more than one entry.

Relationship traversal is small, deterministic and bounded:

    - breadth-first from each matched item, following any relation type
      (the vocabulary is open - pass `relation_types` to restrict it),
      from either side of a relationship, in the deterministic order
      `relationships_for()` returns;
    - `max_depth` hops (default DEFAULT_MAX_DEPTH = 1, hard cap
      MAX_DEPTH_LIMIT = 3; 0 disables traversal);
    - at most `max_related` entries per matched item (default
      DEFAULT_MAX_RELATED = 10, hard cap MAX_RELATED_LIMIT = 50). A node
      is only expanded (one `relationships_for()` call) after it has been
      emitted as an entry, so a hub with thousands of neighbours costs at
      most max_related + 1 expansions - never one per neighbour;
    - at most MAX_MATCHED_ITEMS matched items per call;
    - every DIRECT relationship of the matched item is reported (two
      relations to the same target, say a translation and a related
      meaning, are two facts); beyond the first hop a node is reported
      once, at its shortest distance, so a densely connected graph cannot
      spend the budget repeating what was already reported;
    - each node is expanded at most once and a relationship is reported at
      most once, so cycles terminate and the walk never reports the
      matched item back to itself;
    - a value above a hard cap is clamped to it (the limits actually
      applied are reported in `limits`), and `truncated` is True whenever
      something reachable was left out because of max_related or
      MAX_MATCHED_ITEMS. Stopping at `max_depth` is the declared scope,
      not truncation.

Cost note: each expansion is one relationship read for that node, which
loads that node's own relationships before ordering them. A language-less
lookup also reads by written form without a dedicated index (a language
narrows it via the existing unique index); both are fine at on-device
scale, and a dedicated index would need a schema migration, so it is left
out to keep this stage small.
"""

import copy
from collections import deque

from .language_learning_store import _normalize_key, _require_text, _resolve_language

STATUS_RESOLVED = "RESOLVED"
STATUS_NOT_FOUND = "NOT_FOUND"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_NOT_FOUND)

REASON_UNKNOWN_EXPRESSION = "unknown_expression"
REASON_NO_LEARNED_MEANING = "no_learned_meaning"

DEFAULT_MAX_DEPTH = 1
MAX_DEPTH_LIMIT = 3
DEFAULT_MAX_RELATED = 10
MAX_RELATED_LIMIT = 50
MAX_MATCHED_ITEMS = 10


def _is_empty(value):
    """True for the 'nothing stored' shapes (None, blank text, empty
    list/dict). 0 and False are real values, not empty."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _bounded(value, name, default, hard_cap):
    """None -> default; otherwise a non-negative int, clamped to the hard
    cap. Anything else is a caller error."""
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int or None")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return min(value, hard_cap)


def _item_identity(item):
    return {
        "kind": "item", "id": item["id"], "language": item["language"],
        "item_type": item["item_type"], "key": item["key"],
    }


def _node_id(endpoint):
    """Stable identity of a graph node, for cycle/visited tracking."""
    if endpoint["kind"] == "item":
        return ("item", endpoint["id"])
    return ("concept", endpoint["concept"])


def _endpoint_identity(endpoint):
    if endpoint["kind"] == "item":
        return {
            "kind": "item", "id": endpoint["id"], "language": endpoint["language"],
            "item_type": endpoint["item_type"], "key": endpoint["key"],
        }
    return {"kind": "concept", "concept": endpoint["concept"], "language": None}


class MeaningResolutionResult:
    """Plain, JSON-shaped result - same `to_dict()` convention used
    throughout this package. Never constructed by a caller;
    `MeaningResolver.resolve()` returns these.

        status          STATUS_RESOLVED or STATUS_NOT_FOUND
        expression      the expression exactly as asked
        language        the canonical language asked for, or None when no
                        language was given (every language is searched)
        item_type       the item_type asked for, or None
        meanings        one entry per matched item that carries learned
                        meaning (see `MeaningResolver.resolve`); [] when
                        NOT_FOUND
        ambiguous       True when `meanings` has more than one entry
        matched_items   identity of every learned item the expression
                        matched, meaning-bearing or not - how a caller
                        tells an unknown expression from a known one that
                        has no learned meaning yet
        reason          None when RESOLVED; else REASON_*
        truncated       True when a bound cut off something reachable
        limits          the bounds actually applied
        variation_match Prompt 438, optional: when this resolver was
                        constructed with a `variation_matcher` and no
                        DIRECT item matched `expression`, the
                        `LearnedExpressionVariationMatcher` result (as a
                        dict) consulted as a fallback - None when no
                        matcher was given, or a direct match was already
                        found and the matcher was never consulted. A
                        MATCHED variation result means `meanings` above
                        was resolved through the matched learned
                        expression, not `expression` itself; an
                        AMBIGUOUS or NOT_FOUND one is kept here for
                        transparency only - it never changes `status`
                        away from NOT_FOUND (nothing here is guessed).
    """

    def __init__(self, status, expression, language, item_type, meanings, matched_items,
                 reason, truncated, limits, variation_match=None):
        self.status = status
        self.expression = expression
        self.language = language
        self.item_type = item_type
        self.meanings = meanings
        self.matched_items = matched_items
        self.reason = reason
        self.truncated = truncated
        self.limits = limits
        self.variation_match = variation_match

    @property
    def resolved(self):
        return self.status == STATUS_RESOLVED

    @property
    def ambiguous(self):
        return len(self.meanings) > 1

    def __repr__(self):
        return (
            f"MeaningResolutionResult(status={self.status!r}, expression={self.expression!r}, "
            f"language={self.language!r}, meanings={len(self.meanings)}, reason={self.reason!r})"
        )

    def to_dict(self):
        return copy.deepcopy({
            "status": self.status,
            "expression": self.expression,
            "language": self.language,
            "item_type": self.item_type,
            "meanings": self.meanings,
            "ambiguous": self.ambiguous,
            "matched_items": self.matched_items,
            "reason": self.reason,
            "truncated": self.truncated,
            "limits": self.limits,
            "variation_match": self.variation_match,
        })


class MeaningResolver:
    """Composes an existing `LanguageLearningStore`,
    `LanguageRelationshipStore` and `KnowledgeSystem` - owns no storage and
    writes nothing. Every call is a deterministic, bounded read.

    `variation_matcher` (Prompt 438, optional): a
    `LearnedExpressionVariationMatcher` (learned_expression_variation_matcher.py).
    Left as None (the default), behaviour is IDENTICAL to before Prompt
    438 - this argument is purely additive. When given, `resolve()`
    consults it ONLY as a fallback, after `find_items()` finds no direct
    match for `expression` at all - never in place of, and never before,
    the existing direct lookup (see that module's own docstring: "do not
    replace the existing exact-expression matching")."""

    def __init__(self, language_learning, language_relationships, knowledge=None,
                 variation_matcher=None):
        self.language_learning = language_learning
        self.relationships = language_relationships
        self.knowledge = knowledge if knowledge is not None else language_relationships.knowledge
        self.variation_matcher = variation_matcher

    # ------------------------------------------------------------------
    def resolve(self, expression, language=None, item_type=None, relation_types=None,
                max_depth=None, max_related=None):
        """Resolve the learned meaning of `expression` (RAW / labelled view).

        Prompt 673: this public lookup is unchanged - a concept endpoint is
        reported together with its stored `status` (a concept whose status is
        "inactive" is still listed, labelled). Conversational understanding uses
        `resolve_current()` below instead.

        Resolve the learned meaning of `expression`.

        `language` / `item_type` narrow which learned items match (see the
        module docstring for language=None). `relation_types` (an iterable
        of labels, case/whitespace-insensitive; None = any type) restricts
        which relationships are followed. `max_depth` / `max_related` set
        the traversal bounds, clamped to their hard caps.

        Each entry of the result's `meanings` describes one matched item:

            language, item_type, key, id   which learned item this is
            meaning, examples              its stored, uninterpreted values
            confidence, source, source_context, learning_method
                                           its stored provenance
            has_stored_meaning             True if `meaning` is non-empty
            related                        the relationships followed:
                                           each {relation_type, direction,
                                           depth, via, confidence,
                                           metadata, related} where
                                           `related` is the reached item
                                           (with its own stored meaning /
                                           examples) or concept (with its
                                           description / status)
            related_truncated              True if max_related cut it off

        Raises ValueError/TypeError for a malformed argument (blank
        expression, a placeholder language, a negative or non-int bound).
        An expression the system knows nothing about is NOT an error - it
        is a NOT_FOUND result."""
        return self._resolve(expression, language, item_type, relation_types,
                             max_depth, max_related, current_only=False)

    def resolve_current(self, expression, language=None, item_type=None, relation_types=None,
                        max_depth=None, max_related=None):
        """Prompt 673: `resolve()` for CURRENT conversational use.

        Identical to `resolve()` (same arguments, bounds, ordering, result shape,
        read-only) except that a relationship whose reached endpoint is a Knowledge
        concept with stored status "inactive" (Prompt 663) is not followed: it is not
        reported, not expanded, and does not count toward `max_related` or make the
        item RESOLVED on its own. A concept endpoint is an EXACT stored name, so the
        check is on that exact record - an active case-variant is never substituted
        for an inactive endpoint (and an inactive variant never hides an active one).
        Stub / legacy-status / missing concept rows and language-item endpoints are
        unaffected. `resolve()` keeps its raw, labelled contract."""
        return self._resolve(expression, language, item_type, relation_types,
                             max_depth, max_related, current_only=True)

    def _resolve(self, expression, language, item_type, relation_types, max_depth,
                 max_related, current_only):
        expression = _require_text(expression, "expression")
        language = _resolve_language(language) if language is not None else None
        if item_type is not None:
            item_type = _require_text(item_type, "item_type")
        depth = _bounded(max_depth, "max_depth", DEFAULT_MAX_DEPTH, MAX_DEPTH_LIMIT)
        related_cap = _bounded(max_related, "max_related", DEFAULT_MAX_RELATED, MAX_RELATED_LIMIT)
        allowed_types = self._normalize_relation_types(relation_types)
        limits = {
            "max_depth": depth, "max_related": related_cap, "max_matched_items": MAX_MATCHED_ITEMS,
        }

        found = self.language_learning.find_items(
            expression, language=language, item_type=item_type, limit=MAX_MATCHED_ITEMS + 1,
        )
        truncated = len(found) > MAX_MATCHED_ITEMS
        found = found[:MAX_MATCHED_ITEMS]

        variation_match = None
        if not found and self.variation_matcher is not None:
            # Prompt 438 fallback: `expression` matched no learned item
            # at all directly - see whether an EXPLICIT, already-stored
            # relationship connects it to one. Never consulted when a
            # direct match already exists.
            variation_result = self.variation_matcher.match(
                expression, language=language, item_type=item_type,
            )
            variation_match = variation_result.to_dict()
            if variation_result.matched:
                matched_expression = variation_result.candidate["matched_expression"]
                matched_language = variation_result.candidate["language"]
                matched_item_type = variation_result.candidate["item_type"]
                variation_item = self.language_learning.get_item(
                    matched_language, matched_item_type, matched_expression,
                )
                if variation_item is not None:
                    found = [variation_item]
            # AMBIGUOUS or NOT_FOUND: `found` stays empty - nothing here
            # picks a candidate on the resolver's behalf (requirement 7).

        matched_via_variation = variation_match is not None and variation_match["status"] == "MATCHED"
        meanings = []
        for item in found:
            related, related_truncated = self._collect_related(
                item, allowed_types, depth, related_cap, current_only)
            has_stored_meaning = not _is_empty(item["meaning"])
            if not (has_stored_meaning or related or related_truncated):
                continue  # a known item with nothing learned about its meaning
            truncated = truncated or related_truncated
            meanings.append({
                "language": item["language"], "item_type": item["item_type"],
                "key": item["key"], "id": item["id"],
                "meaning": item["meaning"], "examples": item["examples"],
                "confidence": item["confidence"], "source": item["source"],
                "source_context": item["source_context"],
                "learning_method": item["learning_method"],
                "has_stored_meaning": has_stored_meaning,
                "related": related, "related_truncated": related_truncated,
                "matched_via_variation": matched_via_variation,
            })

        if meanings:
            status, reason = STATUS_RESOLVED, None
        else:
            status = STATUS_NOT_FOUND
            reason = REASON_NO_LEARNED_MEANING if found else REASON_UNKNOWN_EXPRESSION
        return MeaningResolutionResult(
            status=status, expression=expression, language=language, item_type=item_type,
            meanings=meanings, matched_items=[_item_identity(item) for item in found],
            reason=reason, truncated=truncated, limits=limits, variation_match=variation_match,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_relation_types(relation_types):
        if relation_types is None:
            return None
        if isinstance(relation_types, str):
            relation_types = [relation_types]
        return {_normalize_key(_require_text(t, "relation_types entry")) for t in relation_types}

    def _collect_related(self, item, allowed_types, max_depth, max_related, current_only=False):
        """Bounded breadth-first walk from one matched item. Returns
        (entries, truncated). See the module docstring for the bounds."""
        start = _item_identity(item)
        entries = []
        if max_depth == 0:
            return entries, False

        queued = {_node_id(start)}    # nodes already scheduled for expansion (once each)
        reported = set()              # nodes already emitted as an entry
        seen_relationships = set()    # a relationship is reported at most once
        queue = deque([(start, start, 0)])  # (ref, identity, depth of this node)
        while queue:
            ref, via, depth = queue.popleft()
            for relationship in self.relationships.relationships_for(ref):
                if allowed_types is not None and (
                    _normalize_key(relationship["relation_type"]) not in allowed_types
                ):
                    continue
                if relationship["id"] in seen_relationships:
                    continue
                related = relationship["related"]
                if current_only and self._is_inactive_concept(related):
                    continue  # Prompt 673: inactive concepts do not take part in current use
                node = _node_id(related)
                if depth > 0 and node in reported:
                    continue  # beyond the first hop, report each node once
                if len(entries) >= max_related:
                    return entries, True
                seen_relationships.add(relationship["id"])
                reported.add(node)
                entries.append(self._entry(relationship, depth + 1, via))
                if depth + 1 < max_depth and node not in queued:
                    queued.add(node)
                    queue.append((related, _endpoint_identity(related), depth + 1))
        return entries, False

    def _is_inactive_concept(self, endpoint):
        """True only for a concept endpoint whose stored status is exactly "inactive"
        (exact-name lookup, read-only). Missing / stub / legacy-status rows are not."""
        if endpoint["kind"] != "concept":
            return False
        row = self.knowledge.get(endpoint["concept"])
        return row is not None and row.get("status") == "inactive"

    def _entry(self, relationship, depth, via):
        return {
            "relation_type": relationship["relation_type"],
            "direction": relationship["direction"],
            "depth": depth,
            "via": via,
            "confidence": relationship["confidence"],
            "metadata": relationship["metadata"],
            "related": self._describe(relationship["related"]),
        }

    def _describe(self, endpoint):
        """The reached endpoint plus what is stored about it: an item's
        own meaning/examples, or a concept's description/status."""
        description = _endpoint_identity(endpoint)
        if endpoint["kind"] == "item":
            stored = self.language_learning.get_item(
                endpoint["language"], endpoint["item_type"], endpoint["key"]
            )
            description["meaning"] = stored["meaning"] if stored else {}
            description["examples"] = stored["examples"] if stored else []
            description["confidence"] = stored["confidence"] if stored else None
        else:
            row = self.knowledge.get(endpoint["concept"])
            description["description"] = row["description"] if row else None
            description["status"] = row["status"] if row else None
        return description
