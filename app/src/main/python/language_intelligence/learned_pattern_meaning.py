"""
Language Intelligence - Learned Pattern Meaning Binding
==========================================================
Prompt 424. One focused capability: an EXPLICITLY TAUGHT link from a
learned sentence pattern to a learned meaning/intention, and the
retrieval of that link when the pattern is recognized.

    binder.bind("fa", "من {{X}} را دوست دارم", "express_preference",
                locale="fa-IR", examples=["من کتاب را دوست دارم"])

    binder.resolve(matcher.match("من چای را دوست دارم", language="fa"))
      -> status RESOLVED, meaning "express_preference",
         variables {"X": "چای"} (from Prompt 421/422, untouched)

This is binding, not interpretation. The caller names the meaning; this
module never derives, guesses or completes one from the sentence, from
its variables, from its examples or from anything else. A pattern with
no bound meaning is reported as having none (`STATUS_NOT_FOUND`, with the
same `REASON_NO_LEARNED_MEANING` Prompt 418 already uses) and the match
is returned exactly as it was.

Reuse map (this stage adds no storage, no matcher, no pattern model, no
meaning-resolution system and no disambiguation system):

    the pattern         a Prompt 416 item of `item_type=ITEM_TYPE_PATTERN`
                        taught through Prompt 423. Binding never creates
                        a pattern: an unknown pattern is refused
                        (STATUS_PATTERN_NOT_FOUND) instead of being
                        taught implicitly.
    the meaning         a Prompt 416 item of `item_type="meaning"` (the
                        very use Prompt 417's docstring anticipates: "a
                        'meaning' can be learned as an item of item_type
                        'meaning'"), in the pattern's own language. Its
                        key is the meaning's name/id text, verbatim
                        ("express_preference"); its row id is the meaning
                        ID. The same name in two languages is two items.
    the link            a Prompt 417 relationship, `relation_type=
                        RELATION_PATTERN_MEANING`, directed pattern ->
                        meaning, stored by `LanguageRelationshipStore.
                        relate()` in the existing
                        `language_item_relationships` table. Everything
                        specific to ONE binding lives on that row and
                        nowhere else: its `confidence`, `source`,
                        `source_context` (the learning context),
                        `learning_method`, and `metadata` (`locale`,
                        `examples`). It is deliberately NOT stored on the
                        shared meaning item, because one meaning
                        ("express_preference") is bound to many patterns
                        and each binding carries its own context.
    persistence         nothing new: both endpoints and the relationship
                        are ordinary rows of the existing MemorySystem
                        tables, so a reloaded Core/MemorySystem sees the
                        binding exactly as it was.
    pattern recognition `LearnedPatternMatcher.match()` (Prompt 421) and
                        `LearnedSentenceStructureExtractor` (Prompt 422)
                        are not touched. `resolve()` takes the match they
                        already produced (a `LearnedPatternMatchResult`
                        or its `to_dict()`), keeps it whole under
                        `pattern_match`, and repeats its variables.
    disambiguation      several bound meanings are handed, as one
                        resolution-shaped record, to the existing
                        `LearnedMeaningDisambiguator` (Prompt 420) and
                        decided by ITS rules - language, active topic,
                        conversation context, resolved references,
                        nearby expressions, and each candidate's own
                        stored examples / learning context. There is no
                        second scoring or selection here; when that
                        layer cannot tell, the status is AMBIGUOUS and
                        every candidate is kept.
    statuses/reasons    `STATUS_RESOLVED` / `STATUS_AMBIGUOUS` /
                        `STATUS_NOT_FOUND` from Prompt 420 and
                        `REASON_NO_LEARNED_MEANING` from Prompt 418.

Binding (`bind`)
-----------------
Validation finishes before anything is written; an invalid request
stores nothing. Errors (each `{"code", "detail"}`, all reported
together): invalid_language, invalid_pattern, invalid_meaning (a
non-empty text name is required - the meaning is never generated),
invalid_locale, locale_language_mismatch, locale_conflicts_with_pattern
(the pattern itself is only recognized under another locale, so the
binding could never apply), invalid_confidence, invalid_source,
invalid_source_context, invalid_examples.

    STATUS_BOUND              a new binding was stored
    STATUS_ALREADY_BOUND      the same pattern -> meaning binding already
                              exists. Only metadata the caller explicitly
                              supplies can change (confidence, source,
                              source_context; new examples are ADDED,
                              never replacing), and only if it differs; a
                              repeat that changes nothing writes nothing.
    STATUS_CONFLICT           the binding exists under another locale; an
                              explicit different locale is reported, not
                              silently re-scoped. Nothing changed.
    STATUS_PATTERN_NOT_FOUND  no such learned pattern (nothing stored)
    STATUS_INVALID            refused, nothing stored

A pattern may be bound to several meanings (each its own binding); the
same meaning may be bound to several patterns.

Retrieval (`resolve`)
----------------------
    original_message   the message exactly as the caller gave it
                       (`original_message=` lets the Understanding Engine
                       pass the user's untouched text although the matcher
                       was handed the normalized one)
    pattern_match      the Prompt 421 match, whole and unchanged
    variables          the match's extracted variables (Prompt 422 reads
                       the same ones)
    status             RESOLVED (exactly one applies), AMBIGUOUS (several
                       bound and the existing disambiguator could not
                       tell) or NOT_FOUND, with `reason`:
        REASON_PATTERN_NOT_MATCHED   the message did not MATCH a single
                                     learned pattern (NOT_FOUND / AMBIGUOUS
                                     / NOT_RESOLVED in Prompt 421): no
                                     pattern is identified, so no
                                     meaning is looked up, let alone
                                     guessed
        REASON_NO_LEARNED_MEANING    the pattern matched but has no
                                     bound meaning (Prompt 418's reason)
        REASON_NO_MEANING_FOR_LOCALE meanings are bound but none applies
                                     under the requested locale
        plus the Prompt 420 REASON_* of the disambiguation otherwise.
    meaning            the one RESOLVED candidate, else None
    candidates         EVERY applicable bound meaning, never collapsed
                       (also when one was selected)
    language / locale  the language the pattern was learned in; the
                       locale asked for (a binding that names another
                       locale is left out; a binding without a locale
                       applies to every locale, the Prompt 421 rule)
    disambiguation     the Prompt 420 `DisambiguationResult.to_dict()`
                       when several candidates were decided between

One candidate (`meaning`, `candidates[i]`) carries: `id` / `meaning_id`
(the meaning item's id), `key` / `meaning_name`, `language`, `locale`,
`confidence`, `source`, `source_context`, `learning_method`, `examples`
(the binding's), `binding_id`, `pattern_id`, `item_type`, `meaning` (the
meaning item's own stored value, uninterpreted), `related` ([]).

`resolve()` reads only; it writes nothing, not even a learning event.
"""

import copy

from .language_learning_store import (
    ITEM_TYPE_PATTERN, _resolve_language, _clamp_confidence, _require_text,
)
from .language_relationships import item_ref
from .learned_meaning_disambiguation import (
    LearnedMeaningDisambiguator, STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND,
)
from .learned_pattern_matching import STATUS_MATCHED, _pattern_locale
from .learned_pattern_teaching import _validate_locale, _language_base, _is_real_number, _issue
from .meaning_resolution import REASON_NO_LEARNED_MEANING, _bounded

ITEM_TYPE_MEANING = "meaning"
RELATION_PATTERN_MEANING = "pattern_meaning"

STATUS_BOUND = "BOUND"
STATUS_ALREADY_BOUND = "ALREADY_BOUND"
STATUS_CONFLICT = "CONFLICT"
STATUS_PATTERN_NOT_FOUND = "PATTERN_NOT_FOUND"
STATUS_INVALID = "INVALID"
ALL_BINDING_STATUSES = (
    STATUS_BOUND, STATUS_ALREADY_BOUND, STATUS_CONFLICT, STATUS_PATTERN_NOT_FOUND,
    STATUS_INVALID,
)
ALL_MEANING_STATUSES = (STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)

REASON_PATTERN_BOUND = "pattern_meaning_bound"
REASON_IDENTICAL_BINDING_EXISTS = "identical_binding_already_learned"
REASON_LOCALE_DIFFERS = "binding_exists_with_different_locale"
REASON_UNKNOWN_PATTERN = "unknown_pattern"
REASON_PATTERN_NOT_MATCHED = "learned_pattern_not_matched"
REASON_NO_MEANING_FOR_LOCALE = "no_bound_meaning_for_locale"

ERROR_INVALID_LANGUAGE = "invalid_language"
ERROR_INVALID_PATTERN = "invalid_pattern"
ERROR_INVALID_MEANING = "invalid_meaning"
ERROR_INVALID_LOCALE = "invalid_locale"
ERROR_LOCALE_LANGUAGE_MISMATCH = "locale_language_mismatch"
ERROR_LOCALE_CONFLICTS_WITH_PATTERN = "locale_conflicts_with_pattern"
ERROR_INVALID_CONFIDENCE = "invalid_confidence"
ERROR_INVALID_SOURCE = "invalid_source"
ERROR_INVALID_SOURCE_CONTEXT = "invalid_source_context"
ERROR_INVALID_EXAMPLES = "invalid_examples"

LEARNING_METHOD = "explicit_pattern_meaning_binding"

DEFAULT_MAX_MEANINGS = 10
MAX_MEANINGS_LIMIT = 50


def _dedupe(values):
    seen, unique = set(), []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _binding_locale(relationship):
    metadata = relationship.get("metadata")
    return metadata.get("locale") if isinstance(metadata, dict) else None


def _binding_examples(relationship):
    metadata = relationship.get("metadata")
    examples = metadata.get("examples") if isinstance(metadata, dict) else None
    return list(examples) if isinstance(examples, list) else []


class PatternMeaningBindingResult:
    """Plain, JSON-shaped result of `LearnedPatternMeaningBinder.bind()`.

        status          one of ALL_BINDING_STATUSES
        success         True for BOUND and ALREADY_BOUND
        created         True exactly for BOUND
        updated_fields  fields of an EXISTING binding this call changed
                        (subset of "confidence", "source", "source_context",
                        "examples"); [] otherwise
        binding         the stored binding as a candidate dict (see the
                        module docstring), or None
        pattern_id, pattern_text, meaning_id, meaning_name, language,
        locale, confidence, source, source_context, examples
                        as stored (None / [] when nothing was stored)
        errors          why INVALID / CONFLICT / PATTERN_NOT_FOUND:
                        `{"code", "detail"}` entries
        reason          a REASON_* constant, or the first error code
    """

    def __init__(self, status, reason, binding=None, pattern_id=None, pattern_text=None,
                 language=None, created=False, updated_fields=None, errors=None):
        self.status = status
        self.reason = reason
        self.binding = binding
        self.pattern_id = pattern_id
        self.pattern_text = pattern_text
        self.language = language
        self.created = created
        self.updated_fields = updated_fields if updated_fields is not None else []
        self.errors = errors if errors is not None else []

    @property
    def success(self):
        return self.status in (STATUS_BOUND, STATUS_ALREADY_BOUND)

    def _from_binding(self, key):
        return self.binding.get(key) if self.binding else None

    meaning_id = property(lambda self: self._from_binding("meaning_id"))
    meaning_name = property(lambda self: self._from_binding("meaning_name"))
    locale = property(lambda self: self._from_binding("locale"))
    confidence = property(lambda self: self._from_binding("confidence"))
    source = property(lambda self: self._from_binding("source"))
    source_context = property(lambda self: self._from_binding("source_context"))
    examples = property(lambda self: list(self._from_binding("examples") or []))

    def __repr__(self):
        return (f"PatternMeaningBindingResult(status={self.status!r}, "
                f"pattern_id={self.pattern_id!r}, meaning_name={self.meaning_name!r}, "
                f"reason={self.reason!r})")

    def to_dict(self):
        return {
            "status": self.status,
            "success": self.success,
            "created": self.created,
            "updated_fields": list(self.updated_fields),
            "binding": dict(self.binding) if self.binding else None,
            "pattern_id": self.pattern_id,
            "pattern_text": self.pattern_text,
            "meaning_id": self.meaning_id,
            "meaning_name": self.meaning_name,
            "language": self.language,
            "locale": self.locale,
            "confidence": self.confidence,
            "source": self.source,
            "source_context": self.source_context,
            "examples": self.examples,
            "errors": [dict(e) for e in self.errors],
            "reason": self.reason,
        }


class LearnedPatternMeaningResult:
    """Plain, JSON-shaped result of `LearnedPatternMeaningBinder.resolve()`
    - see the module docstring's "Retrieval" section for every field.
    `pattern_match` is the Prompt 421 match, whole and unchanged."""

    def __init__(self, original_message, pattern_match, status, reason, meaning, candidates,
                 language, locale, disambiguation, truncated, limits):
        self.original_message = original_message
        self.pattern_match = pattern_match
        self.status = status
        self.reason = reason
        self.meaning = meaning
        self.candidates = candidates
        self.language = language
        self.locale = locale
        self.disambiguation = disambiguation
        self.truncated = truncated
        self.limits = limits

    @property
    def resolved(self):
        return self.status == STATUS_RESOLVED

    @property
    def ambiguous(self):
        return self.status == STATUS_AMBIGUOUS

    @property
    def matched(self):
        return bool(self.pattern_match and self.pattern_match.get("status") == STATUS_MATCHED)

    @property
    def variables(self):
        return dict(self.pattern_match.get("variables") or {}) if self.pattern_match else {}

    @property
    def matched_pattern_id(self):
        return self.pattern_match.get("matched_pattern_id") if self.pattern_match else None

    @property
    def matched_pattern_text(self):
        return self.pattern_match.get("matched_pattern_text") if self.pattern_match else None

    @property
    def meaning_name(self):
        return self.meaning["meaning_name"] if self.meaning else None

    def __repr__(self):
        return (f"LearnedPatternMeaningResult(status={self.status!r}, "
                f"meaning_name={self.meaning_name!r}, candidates={len(self.candidates)}, "
                f"reason={self.reason!r})")

    def to_dict(self):
        return {
            "original_message": self.original_message,
            "status": self.status,
            "resolved": self.resolved,
            "ambiguous": self.ambiguous,
            "matched": self.matched,
            "matched_pattern_id": self.matched_pattern_id,
            "matched_pattern_text": self.matched_pattern_text,
            "variables": self.variables,
            "pattern_match": copy.deepcopy(self.pattern_match),
            "meaning": dict(self.meaning) if self.meaning else None,
            "meaning_name": self.meaning_name,
            "candidates": [dict(c) for c in self.candidates],
            "language": self.language,
            "locale": self.locale,
            "disambiguation": self.disambiguation,
            "reason": self.reason,
            "truncated": self.truncated,
            "limits": dict(self.limits),
        }


class LearnedPatternMeaningBinder:
    """Composes an existing `LanguageLearningStore` (Prompt 416) and
    `LanguageRelationshipStore` (Prompt 417) - owns no storage - plus the
    existing stateless `LearnedMeaningDisambiguator` (Prompt 420; Core
    passes its own). `bind()` writes; `resolve()` / `bindings_for()` only
    read. Stateless: one instance is safe to reuse for every call."""

    def __init__(self, language_learning, language_relationships, disambiguator=None):
        self.language_learning = language_learning
        self.relationships = language_relationships
        self.disambiguator = (
            disambiguator if disambiguator is not None else LearnedMeaningDisambiguator()
        )

    # ------------------------------------------------------------------
    # Binding
    # ------------------------------------------------------------------
    def bind(self, language, pattern, meaning, locale=None, confidence=None, source=None,
             source_context=None, examples=None):
        """Explicitly bind the learned `pattern` (already taught for
        `language`) to the meaning/intention named `meaning`. See the
        module docstring for validation, duplicate and locale rules.
        Returns a `PatternMeaningBindingResult`; never raises for bad
        input."""
        errors = []
        resolved_language = None
        try:
            resolved_language = _resolve_language(language)
        except (ValueError, TypeError) as error:
            errors.append(_issue(ERROR_INVALID_LANGUAGE, str(error)))

        if not isinstance(pattern, str) or not pattern.strip():
            errors.append(_issue(ERROR_INVALID_PATTERN, "pattern must be a non-empty string"))
        if not isinstance(meaning, str) or not meaning.strip():
            errors.append(_issue(
                ERROR_INVALID_MEANING,
                "meaning must be the non-empty text name of a meaning/intention; "
                "it is never generated"))

        explicit_locale, error = _validate_locale(locale, "locale")
        if error:
            errors.append(error)
        elif explicit_locale and resolved_language is not None:
            if _language_base(explicit_locale) != _language_base(language):
                errors.append(_issue(
                    ERROR_LOCALE_LANGUAGE_MISMATCH,
                    f"locale {explicit_locale!r} does not belong to language {language!r}"))

        if confidence is not None and not _is_real_number(confidence):
            errors.append(_issue(ERROR_INVALID_CONFIDENCE,
                                 "confidence must be a finite number or None"))
        if source is not None and (not isinstance(source, str) or not source.strip()):
            errors.append(_issue(ERROR_INVALID_SOURCE, "source must be a non-empty string or None"))
        if source_context is not None and (
                not isinstance(source_context, str) or not source_context.strip()):
            errors.append(_issue(ERROR_INVALID_SOURCE_CONTEXT,
                                 "source_context must be a non-empty string or None"))
        example_list = []
        if examples is not None:
            if not isinstance(examples, (list, tuple)):
                errors.append(_issue(ERROR_INVALID_EXAMPLES,
                                     "examples must be a list of strings or None"))
            else:
                bad = [i for i, e in enumerate(examples) if not isinstance(e, str) or not e.strip()]
                if bad:
                    errors.append(_issue(
                        ERROR_INVALID_EXAMPLES,
                        f"examples at positions {bad} are not non-empty strings", positions=bad))
                else:
                    example_list = _dedupe(examples)

        pattern_item = None
        if not errors:
            pattern_item = self.language_learning.get_item(
                resolved_language, ITEM_TYPE_PATTERN, pattern)
            if pattern_item is None:
                return PatternMeaningBindingResult(
                    STATUS_PATTERN_NOT_FOUND, REASON_UNKNOWN_PATTERN, pattern_text=pattern,
                    language=resolved_language,
                    errors=[_issue(REASON_UNKNOWN_PATTERN,
                                   "no such learned pattern; teach it first - binding never "
                                   "creates a pattern")])
            pattern_locale = _pattern_locale(pattern_item)
            if explicit_locale and pattern_locale and explicit_locale != pattern_locale:
                errors.append(_issue(
                    ERROR_LOCALE_CONFLICTS_WITH_PATTERN,
                    f"the pattern is only recognized under locale {pattern_locale!r}"))

        if errors:
            return PatternMeaningBindingResult(
                STATUS_INVALID, errors[0]["code"],
                pattern_text=pattern if isinstance(pattern, str) else None,
                language=resolved_language, errors=errors)

        name = meaning.strip()
        clamped_confidence = _clamp_confidence(confidence)
        pattern_ref = item_ref(pattern_item["language"], ITEM_TYPE_PATTERN, pattern_item["key"])

        meaning_item = self.language_learning.get_item(resolved_language, ITEM_TYPE_MEANING, name)
        existing = None
        if meaning_item is not None:
            existing = self._find_binding(pattern_ref, meaning_item["id"])

        if existing is None:
            return self._create(pattern_ref, pattern_item, meaning_item, name, explicit_locale,
                                clamped_confidence, source, source_context, example_list)
        return self._update(existing, pattern_item, meaning_item, explicit_locale,
                            clamped_confidence, source, source_context, example_list)

    def _create(self, pattern_ref, pattern_item, meaning_item, name, locale, confidence, source,
                source_context, examples):
        if meaning_item is None:
            meaning_item = self.language_learning.learn_item(
                pattern_item["language"], ITEM_TYPE_MEANING, name, source=source,
                learning_method=LEARNING_METHOD)
        metadata = {}
        if locale is not None:
            metadata["locale"] = locale
        if examples:
            metadata["examples"] = examples
        relationship = self.relationships.relate(
            pattern_ref, item_ref(meaning_item["language"], ITEM_TYPE_MEANING, meaning_item["key"]),
            RELATION_PATTERN_MEANING, symmetric=False, metadata=metadata or None,
            confidence=confidence, source=source, source_context=source_context,
            learning_method=LEARNING_METHOD)
        return PatternMeaningBindingResult(
            STATUS_BOUND, REASON_PATTERN_BOUND,
            binding=self._candidate(relationship, pattern_item, meaning_item),
            pattern_id=pattern_item["id"], pattern_text=pattern_item["key"],
            language=pattern_item["language"], created=True)

    def _update(self, existing, pattern_item, meaning_item, locale, confidence, source,
                source_context, examples):
        stored_locale = _binding_locale(existing)
        if locale is not None and locale != stored_locale:
            return PatternMeaningBindingResult(
                STATUS_CONFLICT, REASON_LOCALE_DIFFERS,
                binding=self._candidate(existing, pattern_item, meaning_item),
                pattern_id=pattern_item["id"], pattern_text=pattern_item["key"],
                language=pattern_item["language"],
                errors=[_issue(REASON_LOCALE_DIFFERS,
                               f"the stored binding has locale {stored_locale!r}; "
                               f"{locale!r} was given")])

        updated = []
        if confidence is not None and confidence != existing["confidence"]:
            updated.append("confidence")
        if source is not None and source != existing["source"]:
            updated.append("source")
        if source_context is not None and source_context != existing["source_context"]:
            updated.append("source_context")
        stored_examples = _binding_examples(existing)
        added = [e for e in examples if e not in stored_examples]
        if added:
            updated.append("examples")

        current = existing
        if updated:
            metadata = dict(existing.get("metadata") or {})
            if stored_locale is not None:
                metadata["locale"] = stored_locale
            if added:
                metadata["examples"] = stored_examples + added
            current = self.relationships.relate(
                item_ref(pattern_item["language"], ITEM_TYPE_PATTERN, pattern_item["key"]),
                item_ref(meaning_item["language"], ITEM_TYPE_MEANING, meaning_item["key"]),
                RELATION_PATTERN_MEANING, symmetric=False, metadata=metadata or None,
                confidence=confidence, source=source, source_context=source_context)
        return PatternMeaningBindingResult(
            STATUS_ALREADY_BOUND, REASON_IDENTICAL_BINDING_EXISTS,
            binding=self._candidate(current, pattern_item, meaning_item),
            pattern_id=pattern_item["id"], pattern_text=pattern_item["key"],
            language=pattern_item["language"], updated_fields=updated)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def bindings_for(self, language, pattern, locale=None, max_meanings=None):
        """Every meaning explicitly bound to the learned `pattern`, as
        candidate dicts (see the module docstring), narrowed by `locale`
        the way Prompt 421 narrows patterns. [] when the pattern is
        unknown or has none. Read-only."""
        cap = _bounded(max_meanings, "max_meanings", DEFAULT_MAX_MEANINGS, MAX_MEANINGS_LIMIT)
        pattern_item = self.language_learning.get_item(
            _resolve_language(language), ITEM_TYPE_PATTERN, _require_text(pattern, "pattern"))
        if pattern_item is None:
            return []
        candidates, _, _ = self._collect(pattern_item, locale, cap)
        return candidates

    def resolve(self, match, locale=None, original_message=None, active_topic=None,
                conversation_context=None, resolved_reference=None, nearby_expressions=None,
                preferred_language=None, max_meanings=None):
        """The explicitly bound meaning of the pattern `match` recognized.

        `match` is the `LearnedPatternMatchResult` (or its `to_dict()`)
        Prompt 421 produced - never re-matched here. `locale` defaults to
        the locale the match itself was made under. Every other argument
        is optional, read-only context for the existing Prompt 420
        disambiguator (see its docstring); `original_message` overrides
        the message text reported (see the module docstring). Returns a
        `LearnedPatternMeaningResult`. Never guesses and never writes."""
        cap = _bounded(max_meanings, "max_meanings", DEFAULT_MAX_MEANINGS, MAX_MEANINGS_LIMIT)
        limits = {"max_meanings": cap}
        match_dict = match if isinstance(match, dict) else match.to_dict()
        message = original_message if original_message is not None else (
            match_dict.get("original_message"))
        language = match_dict.get("language")
        if locale is None:
            locale = match_dict.get("locale")

        def result(status, reason, meaning=None, candidates=None, disambiguation=None,
                   truncated=False):
            return LearnedPatternMeaningResult(
                message, match_dict, status, reason, meaning, candidates or [], language, locale,
                disambiguation, truncated, limits)

        if (match_dict.get("status") != STATUS_MATCHED
                or match_dict.get("matched_pattern_id") is None):
            return result(STATUS_NOT_FOUND, REASON_PATTERN_NOT_MATCHED)

        pattern_item = self.language_learning.get_item(
            language, ITEM_TYPE_PATTERN, match_dict["matched_pattern_text"])
        if pattern_item is None or pattern_item["id"] != match_dict["matched_pattern_id"]:
            return result(STATUS_NOT_FOUND, REASON_PATTERN_NOT_MATCHED)

        candidates, truncated, excluded = self._collect(pattern_item, locale, cap)
        if not candidates:
            reason = REASON_NO_MEANING_FOR_LOCALE if excluded else REASON_NO_LEARNED_MEANING
            return result(STATUS_NOT_FOUND, reason)

        resolution = {
            "status": STATUS_RESOLVED, "expression": pattern_item["key"],
            "language": pattern_item["language"], "item_type": ITEM_TYPE_PATTERN,
            "meanings": candidates, "ambiguous": len(candidates) > 1,
            "matched_items": [{
                "kind": "item", "id": pattern_item["id"], "language": pattern_item["language"],
                "item_type": ITEM_TYPE_PATTERN, "key": pattern_item["key"],
            }],
            "reason": None, "truncated": truncated, "limits": dict(limits),
        }
        decision = self.disambiguator.disambiguate(
            resolution, language=pattern_item["language"], active_topic=active_topic,
            conversation_context=conversation_context, resolved_reference=resolved_reference,
            nearby_expressions=nearby_expressions, preferred_language=preferred_language)
        chosen = decision.resolved_meaning if decision.status == STATUS_RESOLVED else None
        return result(decision.status, decision.reason, meaning=chosen, candidates=candidates,
                      disambiguation=decision.to_dict(), truncated=truncated)

    # ------------------------------------------------------------------
    def _bound_relationships(self, pattern_ref):
        return [
            relationship for relationship in self.relationships.relationships_for(
                pattern_ref, relation_type=RELATION_PATTERN_MEANING)
            if relationship["direction"] == "outgoing"
            and relationship["related"]["kind"] == "item"
            and relationship["related"]["item_type"] == ITEM_TYPE_MEANING
        ]

    def _find_binding(self, pattern_ref, meaning_id):
        for relationship in self._bound_relationships(pattern_ref):
            if relationship["related"]["id"] == meaning_id:
                return relationship
        return None

    def _collect(self, pattern_item, locale, cap):
        """`(candidates, truncated, excluded_by_locale)` - bounded and
        deterministic (relationships_for() order)."""
        pattern_ref = item_ref(pattern_item["language"], ITEM_TYPE_PATTERN, pattern_item["key"])
        candidates, excluded, truncated = [], 0, False
        for relationship in self._bound_relationships(pattern_ref):
            binding_locale = _binding_locale(relationship)
            if locale is not None and binding_locale is not None and binding_locale != locale:
                excluded += 1
                continue
            if len(candidates) >= cap:
                truncated = True
                break
            related = relationship["related"]
            meaning_item = self.language_learning.get_item(
                related["language"], related["item_type"], related["key"])
            candidates.append(self._candidate(relationship, pattern_item, meaning_item))
        return candidates, truncated, excluded

    @staticmethod
    def _candidate(relationship, pattern_item, meaning_item):
        """One binding in the shape Prompt 418/420 meaning entries have
        (`id`, `language`, `key`, `meaning`, `examples`, `confidence`,
        `source`, `source_context`, `learning_method`), plus the binding's
        own identity and locale."""
        return {
            "id": meaning_item["id"], "meaning_id": meaning_item["id"],
            "key": meaning_item["key"], "meaning_name": meaning_item["key"],
            "item_type": ITEM_TYPE_MEANING, "language": meaning_item["language"],
            "locale": _binding_locale(relationship),
            "meaning": meaning_item["meaning"],
            "examples": _binding_examples(relationship),
            "confidence": relationship["confidence"], "source": relationship["source"],
            "source_context": relationship["source_context"],
            "learning_method": relationship["learning_method"],
            "has_stored_meaning": bool(meaning_item["meaning"]), "related": [],
            "related_truncated": False,
            "binding_id": relationship["id"], "pattern_id": pattern_item["id"],
            "relation_type": RELATION_PATTERN_MEANING,
        }
