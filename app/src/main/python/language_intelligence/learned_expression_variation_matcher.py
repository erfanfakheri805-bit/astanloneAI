"""
Language Intelligence - Learned Expression Variation Matching
====================================================================
Prompt 438. One small, focused capability: given a written expression,
decide whether it is (or is EXPLICITLY connected to, through relationship
information already stored) a learned expression - so message
understanding and response-pattern selection can recognize a known
language *variation* of something the system was taught, not only the
exact taught text.

This is a lookup, not understanding. Nothing here invents a synonym, a
translation, a related meaning or a grammatical relation, matches
fuzzily on spelling, or consults a model - the same "structure, don't
fabricate" posture as every other module in this package
(meaning_resolution.py, Prompt 418; learned_pattern_matching.py, Prompt
421). An expression is connected to a learned one ONLY when an existing,
already-stored relationship (Prompt 417) or an exact learned-item match
(Prompt 416) says so.

Reuse map (this stage adds no storage, no matcher database, and no new
kind of intelligence):

    items            LanguageLearningStore (Prompt 416) - the expression
                     is looked up with the SAME case/whitespace-
                     insensitive key identity and `canonical_language()`
                     normalization every other module in this package
                     uses, through its existing, read-only `find_items()`
                     / `get_item()`. No second identity scheme.
    relationships    LanguageRelationshipStore (Prompt 417) - traversal
                     goes only through its public `relationships_for()`,
                     which already carries synonym, translation,
                     related-meaning, grammatical and any other
                     caller-taught relation type, from either side of a
                     stored relationship. No relationship is read any
                     other way, and none is ever created or changed
                     here.
    learned meanings /
    learned expressions /
    learned sentence
    patterns / learned
    pattern meanings     all are, uniformly, `LanguageLearningStore`
                     items (Prompt 416: a "word", "phrase", "pattern" or
                     "meaning" item_type is a caller convention, not a
                     separate table) - so this module needs no per-kind
                     special case to reuse any of them: an item_type
                     filter (or none) is all a caller ever supplies.
    integration      Core owns one instance
                     (`self.expression_variation_matcher`) via one thin
                     passthrough (`match_learned_expression_variation`),
                     and hands the SAME instance to `MeaningResolver`
                     (meaning_resolution.py) and `LearnedPatternMatcher`
                     (learned_pattern_matching.py) as an optional,
                     backward-compatible constructor argument - see
                     each module's own docstring for exactly where it is
                     consulted. `ResponseGenerationResult`,
                     `ConversationResponse`, the local model
                     runtime/provider, model loading, readiness,
                     resource limits, timeout/cancellation, backend
                     selection, memory architecture, reasoning,
                     planning, self-upgrade, web, automation and
                     multimodal systems are untouched.

What "connected" means, precisely
----------------------------------
Given an `expression` (raw text, exactly as given - never rewritten) and
optional `language` / `item_type` / `locale` narrowing:

    1. EXACT match first (this never changes - see the module docstring
       of every module that consults this one: "do not replace the
       existing exact-expression matching"). `find_items()` is asked for
       every learned item whose key equals `expression` under the
       store's own identity rule, narrowed by `language` / `item_type`
       and, when the matched item's own stored `meaning` carries a
       "locale" key (the exact convention `learned_pattern_matching.py`
       already uses for patterns - reused here, not reinvented, for
       every item_type), by `locale`.
           - exactly one such item -> MATCHED, `relation_type="exact"`.
           - more than one (e.g. the same written form was separately
             taught as more than one item_type, or in more than one
             language when `language` was left open) -> AMBIGUOUS; every
             candidate kept, none picked.
           - none -> continue to step 2.
    2. VARIATION match: `expression`'s exact text must ALREADY be some
       OTHER learned item's key (any language/item_type - this is only
       to find a graph node to start from, never a second, fuzzier
       identity rule), found the same `find_items()` way. From each such
       "source" item, every stored relationship touching it
       (`relationships_for()`) is examined:
           - a SYMMETRIC relationship (Prompt 417:
             `SYMMETRIC_BY_DEFAULT`, or explicitly stated symmetric) is
             followed from either side - the two ends are, by
             definition, interchangeable.
           - a relationship that is NOT symmetric (directed) is followed
             only in its stated direction (the source item must be the
             `from` end) - reversing an explicitly directed relationship
             would assert an equivalence nothing taught.
           - the OTHER end must be a learned ITEM (never a concept -
             `expression`-to-`expression` variation only), narrowed by
             `language` / `item_type` / `locale` exactly like step 1.
           - `relation_types` (optional; default: any stored type) can
             narrow which relation types are followed.
       Every distinct reached item is one candidate (a synonym AND a
       translation reaching the same item are still one candidate for
       that item, carrying both relation types is unnecessary - the
       first one found, in `relationships_for()`'s own deterministic
       order, is kept; nothing here re-ranks relation types against each
       other).
           - exactly one candidate -> MATCHED.
           - more than one -> AMBIGUOUS; every candidate kept, and NONE
             is arbitrarily chosen - this is exactly requirement 7's
             "do not arbitrarily choose a candidate".
           - none -> NOT_FOUND. Spelling similarity, semantic intuition
             or any guess is NEVER used as a substitute for a stored
             relationship - requirement 8.

Every candidate (MATCHED or AMBIGUOUS) preserves: the original user
expression, the matched learned expression's text, the relationship type
("exact" for step 1), the matched item's own stored meaning, language,
locale and confidence/source, PLUS (for a step-2 candidate only) the
relationship's own confidence/source and the source item it was reached
through - nothing is collapsed or summarized away.

Deterministic and bounded
--------------------------
No spelling comparison, no embedding, no scoring: `find_items()` is an
exact key lookup and `relationships_for()` is an exact stored-graph read,
both already deterministic and already indexed by the stores this module
composes. Reading is capped so this stage's cost never depends on how
much has been learned: at most `MAX_SOURCE_ITEMS` items with the exact
same text as `expression` are used as starting points (an expression
taught the same way in many languages is unusual; bounding it costs
nothing normal usage would ever notice), and at most `MAX_CANDIDATES`
distinct variation candidates are collected in total. A value above a
hard cap is clamped to it (the limits actually applied are reported in
`limits`), and `truncated` is True whenever something reachable was left
out because of a bound. Repeated calls with the same arguments against
the same stored data always return the same result - nothing here reads
random state, wall-clock time, or anything outside the two composed
stores.
"""

import copy

from .language_learning_store import _normalize_key, _require_text, _resolve_language
from .language_relationships import item_ref

STATUS_MATCHED = "MATCHED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_NOT_FOUND = "NOT_FOUND"
ALL_STATUSES = (STATUS_MATCHED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)

REASON_EXACT_MATCH = "exact_match"
REASON_VARIATION_MATCH = "variation_match"
REASON_MULTIPLE_EXACT_CANDIDATES = "multiple_exact_candidates"
REASON_MULTIPLE_VARIATION_CANDIDATES = "multiple_variation_candidates"
REASON_NO_RELATIONSHIP = "no_explicit_relationship"

RELATION_TYPE_EXACT = "exact"

# Small, fixed bounds - same spirit as meaning_resolution.py's own
# MAX_MATCHED_ITEMS / DEFAULT_MAX_RELATED: keeps this stage's cost
# independent of how much has been learned, without a caller needing to
# think about it on every call.
DEFAULT_MAX_SOURCE_ITEMS = 5
MAX_SOURCE_ITEMS_LIMIT = 20
DEFAULT_MAX_CANDIDATES = 10
MAX_CANDIDATES_LIMIT = 50


def _bounded(value, name, default, hard_cap):
    """None -> default; otherwise a non-negative int, clamped to the
    hard cap - same convention as meaning_resolution.py's own
    `_bounded` / learned_pattern_matching.py's own `_bounded`."""
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int or None")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return min(value, hard_cap)


def _item_locale(item):
    """The locale an item's own stored `meaning` names, using the exact
    convention `learned_pattern_matching.py`'s own `_pattern_locale`
    already applies to patterns - reused here for every item_type
    rather than reinvented."""
    meaning = item.get("meaning")
    if isinstance(meaning, dict):
        return meaning.get("locale")
    return None


def _locale_matches(item, locale):
    if locale is None:
        return True
    return _item_locale(item) is None or _item_locale(item) == locale


def _item_identity(item):
    return {
        "id": item["id"], "language": item["language"],
        "item_type": item["item_type"], "key": item["key"],
    }


class ExpressionVariationCandidate:
    """One candidate connection between `expression` and a learned item -
    plain, JSON-shaped, same `to_dict()` convention used throughout this
    package. Never constructed by a caller directly;
    `LearnedExpressionVariationMatcher.match()` returns these inside a
    `LearnedExpressionVariationMatchResult`.

        original_expression   the expression exactly as asked - Prompt
                              438 requirement 6/12.
        matched_expression     the matched learned item's own `key`,
                              verbatim.
        relation_type          "exact" (step 1), or the stored relation
                              type that connected them (step 2) - never
                              invented.
        meaning                the matched item's own stored `meaning`
                              (Prompt 416; whatever a caller taught it to
                              be - never interpreted here).
        language                the matched item's own `language`.
        locale                  the caller's `locale` argument if given,
                              else the matched item's own stored locale
                              (see `_item_locale`), else None.
        confidence              the matched item's own stored
                              `confidence`.
        source                  the matched item's own stored `source`.
        item_type               the matched item's own `item_type`.
        symmetric                True for a step-1 exact match (trivially
                              reflexive) or a step-2 relationship stored
                              as symmetric; False for a directed one.
        via_expression           for a step-2 candidate, the OTHER
                              learned item's own `key` the relationship
                              was reached through (the item whose text
                              equalled `expression`); None for step 1,
                              where `expression` itself IS the matched
                              item's key.
        relationship_confidence /
        relationship_source     for a step-2 candidate, the STORED
                              relationship's own confidence/source
                              (Prompt 417) - kept distinct from the
                              matched item's own confidence/source so
                              neither provenance is lost; both None for
                              step 1 (there is no relationship - the
                              match is the item itself).
    """

    def __init__(self, original_expression, matched_expression, relation_type, meaning,
                 language, locale, confidence, source, item_type, symmetric,
                 via_expression=None, relationship_confidence=None, relationship_source=None):
        self.original_expression = original_expression
        self.matched_expression = matched_expression
        self.relation_type = relation_type
        self.meaning = meaning
        self.language = language
        self.locale = locale
        self.confidence = confidence
        self.source = source
        self.item_type = item_type
        self.symmetric = symmetric
        self.via_expression = via_expression
        self.relationship_confidence = relationship_confidence
        self.relationship_source = relationship_source

    def to_dict(self):
        return {
            "original_expression": self.original_expression,
            "matched_expression": self.matched_expression,
            "relation_type": self.relation_type,
            "meaning": self.meaning,
            "language": self.language,
            "locale": self.locale,
            "confidence": self.confidence,
            "source": self.source,
            "item_type": self.item_type,
            "symmetric": self.symmetric,
            "via_expression": self.via_expression,
            "relationship_confidence": self.relationship_confidence,
            "relationship_source": self.relationship_source,
        }


class LearnedExpressionVariationMatchResult:
    """Plain, JSON-shaped result - same `to_dict()` convention used
    throughout this package. Never constructed by a caller;
    `LearnedExpressionVariationMatcher.match()` returns these.

        original_expression   the expression exactly as asked, verbatim -
                              never normalized, rewritten or translated.
        status                  one of ALL_STATUSES above.
        matched                  True exactly when status == MATCHED.
        candidate                the single winning `ExpressionVariationCandidate`
                              (as a dict) when status == MATCHED, else
                              None.
        candidates                every candidate this call found, as
                              dicts - the single match again when
                              MATCHED (so a caller never has to look in
                              two places), every candidate when
                              AMBIGUOUS, [] when NOT_FOUND. Never
                              collapsed, never guessed at.
        language / item_type / locale
                              exactly what this call was asked for
                              (echoed, never resolved on the caller's
                              behalf).
        reason                  one of the REASON_* constants above.
        truncated                True when a bound cut off something
                              reachable.
        limits                  the bounds actually applied.
    """

    def __init__(self, original_expression, status, candidates, language, item_type, locale,
                 reason, truncated, limits):
        self.original_expression = original_expression
        self.status = status
        self.candidates = candidates
        self.language = language
        self.item_type = item_type
        self.locale = locale
        self.reason = reason
        self.truncated = truncated
        self.limits = limits

    @property
    def matched(self):
        return self.status == STATUS_MATCHED

    @property
    def candidate(self):
        return self.candidates[0] if self.matched and self.candidates else None

    def __repr__(self):
        return (
            f"LearnedExpressionVariationMatchResult(status={self.status!r}, "
            f"original_expression={self.original_expression!r}, "
            f"candidates={len(self.candidates)}, reason={self.reason!r})"
        )

    def to_dict(self):
        candidate_dicts = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in self.candidates]
        return copy.deepcopy({
            "original_expression": self.original_expression,
            "status": self.status,
            "matched": self.matched,
            "candidate": candidate_dicts[0] if self.matched and candidate_dicts else None,
            "candidates": candidate_dicts,
            "language": self.language,
            "item_type": self.item_type,
            "locale": self.locale,
            "reason": self.reason,
            "truncated": self.truncated,
            "limits": self.limits,
        })


class LearnedExpressionVariationMatcher:
    """Composes an existing `LanguageLearningStore` (Prompt 416) and
    `LanguageRelationshipStore` (Prompt 417) - owns no storage of its
    own and writes nothing. Every call is a deterministic, bounded read.
    Stateless: safe to reuse one instance for every call, same
    convention as `MeaningResolver` / `LearnedPatternMatcher`."""

    def __init__(self, language_learning, language_relationships):
        self.language_learning = language_learning
        self.relationships = language_relationships

    # ------------------------------------------------------------------
    def match(self, expression, language=None, item_type=None, locale=None,
              relation_types=None, max_source_items=None, max_candidates=None):
        """Decide whether `expression` is (or is explicitly connected,
        through an already-stored relationship, to) a learned expression.

        `language` / `item_type` narrow which learned items count as a
        match (see the module docstring); `locale` additionally excludes
        a candidate item that names a different locale in its own stored
        `meaning`. `relation_types` (an iterable of labels, case/
        whitespace-insensitive; None = any stored type) restricts which
        relationships are followed for a variation match. `expression`
        is preserved exactly as given, in `original_expression` and in
        every candidate's `original_expression` - never rewritten.

        Returns a `LearnedExpressionVariationMatchResult`. Never
        guesses: an expression with no exact learned-item match and no
        explicit relationship connecting it to one is NOT_FOUND; more
        than one equally valid candidate (exact or variation) is
        AMBIGUOUS, with every candidate preserved and none picked."""
        expression = _require_text(expression, "expression")
        resolved_language = _resolve_language(language) if language is not None else None
        if item_type is not None:
            item_type = _require_text(item_type, "item_type")
        allowed_types = self._normalize_relation_types(relation_types)
        source_cap = _bounded(
            max_source_items, "max_source_items", DEFAULT_MAX_SOURCE_ITEMS, MAX_SOURCE_ITEMS_LIMIT,
        )
        candidate_cap = _bounded(
            max_candidates, "max_candidates", DEFAULT_MAX_CANDIDATES, MAX_CANDIDATES_LIMIT,
        )
        limits = {
            "max_source_items": source_cap, "max_candidates": candidate_cap,
        }

        # Step 1: exact match - never replaced, always tried first.
        exact_items, exact_truncated = self._find(
            expression, resolved_language, item_type, locale, source_cap,
        )
        if len(exact_items) == 1:
            candidate = self._exact_candidate(expression, exact_items[0], locale).to_dict()
            return LearnedExpressionVariationMatchResult(
                expression, STATUS_MATCHED, [candidate], resolved_language, item_type, locale,
                REASON_EXACT_MATCH, exact_truncated, limits,
            )
        if len(exact_items) > 1:
            candidates = [
                self._exact_candidate(expression, item, locale).to_dict() for item in exact_items
            ]
            return LearnedExpressionVariationMatchResult(
                expression, STATUS_AMBIGUOUS, candidates, resolved_language, item_type, locale,
                REASON_MULTIPLE_EXACT_CANDIDATES, exact_truncated, limits,
            )

        # Step 2: variation match, via an existing, explicit relationship
        # from some OTHER item whose key equals `expression`.
        source_items = self.language_learning.find_items(expression, limit=source_cap + 1)
        source_truncated = len(source_items) > source_cap
        source_items = source_items[:source_cap]

        candidates = []
        seen = set()
        truncated = source_truncated
        for source_item in source_items:
            ref = item_ref(source_item["language"], source_item["item_type"], source_item["key"])
            for relationship in self.relationships.relationships_for(ref, language=resolved_language):
                if allowed_types is not None and (
                    _normalize_key(relationship["relation_type"]) not in allowed_types
                ):
                    continue
                if not relationship["symmetric"] and relationship["direction"] != "outgoing":
                    continue  # a directed relationship is honored only in its stated direction
                related = relationship["related"]
                if related["kind"] != "item":
                    continue  # expression-to-expression variation only, never a concept
                if item_type is not None and related["item_type"] != item_type:
                    continue
                target = self.language_learning.get_item(
                    related["language"], related["item_type"], related["key"]
                )
                if target is None:
                    continue  # the relationship's endpoint no longer resolves; skip, don't guess
                if not _locale_matches(target, locale):
                    continue
                key = (target["language"], target["item_type"], _normalize_key(target["key"]))
                if key in seen:
                    continue
                if len(candidates) >= candidate_cap:
                    truncated = True
                    break
                seen.add(key)
                candidates.append(self._variation_candidate(
                    expression, target, relationship, source_item, locale,
                ).to_dict())

        if len(candidates) == 1:
            return LearnedExpressionVariationMatchResult(
                expression, STATUS_MATCHED, candidates, resolved_language, item_type, locale,
                REASON_VARIATION_MATCH, truncated, limits,
            )
        if len(candidates) > 1:
            return LearnedExpressionVariationMatchResult(
                expression, STATUS_AMBIGUOUS, candidates, resolved_language, item_type, locale,
                REASON_MULTIPLE_VARIATION_CANDIDATES, truncated, limits,
            )
        return LearnedExpressionVariationMatchResult(
            expression, STATUS_NOT_FOUND, [], resolved_language, item_type, locale,
            REASON_NO_RELATIONSHIP, truncated, limits,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_relation_types(relation_types):
        if relation_types is None:
            return None
        if isinstance(relation_types, str):
            relation_types = [relation_types]
        return {_normalize_key(_require_text(t, "relation_types entry")) for t in relation_types}

    def _find(self, expression, language, item_type, locale, cap):
        items = self.language_learning.find_items(
            expression, language=language, item_type=item_type, limit=cap + 1,
        )
        truncated = len(items) > cap
        items = items[:cap]
        items = [item for item in items if _locale_matches(item, locale)]
        return items, truncated

    @staticmethod
    def _exact_candidate(expression, item, locale):
        return ExpressionVariationCandidate(
            original_expression=expression, matched_expression=item["key"],
            relation_type=RELATION_TYPE_EXACT, meaning=item["meaning"], language=item["language"],
            locale=locale if locale is not None else _item_locale(item),
            confidence=item["confidence"], source=item["source"], item_type=item["item_type"],
            symmetric=True,
        )

    @staticmethod
    def _variation_candidate(expression, target, relationship, source_item, locale):
        return ExpressionVariationCandidate(
            original_expression=expression, matched_expression=target["key"],
            relation_type=relationship["relation_type"], meaning=target["meaning"],
            language=target["language"],
            locale=locale if locale is not None else _item_locale(target),
            confidence=target["confidence"], source=target["source"], item_type=target["item_type"],
            symmetric=relationship["symmetric"], via_expression=source_item["key"],
            relationship_confidence=relationship["confidence"], relationship_source=relationship["source"],
        )
