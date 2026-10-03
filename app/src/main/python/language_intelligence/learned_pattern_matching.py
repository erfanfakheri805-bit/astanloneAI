"""
Language Intelligence - Learned Sentence Pattern Matching
==============================================================
Prompt 421. Given a raw message, recognize whether it is an instance of
a sentence *pattern* the system has already been explicitly taught
(Prompt 416, `LanguageLearningStore`, `item_type=ITEM_TYPE_PATTERN`) -
and, if so, which one, with which variable values.

This is NOT a general natural-language model. It never guesses a
pattern that was not explicitly learned, never infers a new grammatical
rule, and never uses probabilistic or ML-based matching - it is a small,
deterministic, structural matcher over what `LanguageLearningStore`
already stores, the exact same "structure, don't fabricate" posture the
rest of this package takes (meaning_resolution.py,
learned_meaning_disambiguation.py).

Reuse map (this stage adds no storage and no new intelligence):

    learned items    `LanguageLearningStore` (Prompt 416) - patterns are
                     read ONLY via its existing, read-only
                     `items_for_language(language, item_type=
                     ITEM_TYPE_PATTERN)` / `languages()`. No second
                     pattern table, no second identity/matching scheme:
                     a pattern is, and is only ever, a
                     `LanguageLearningStore` item of item_type
                     ITEM_TYPE_PATTERN, exactly as that store's own
                     module docstring already anticipates ("a
                     sentence-pattern template").
    language/locale  `language_context.canonical_language()` (Prompt
                     401), via `LanguageLearningStore`'s own
                     `_resolve_language` - the SAME normalization
                     `items_for_language()`/`get_item()` already use, so
                     a pattern taught under "fa" is found under
                     "persian" here exactly as everywhere else in this
                     package. `locale`, which the store itself has no
                     dedicated column for, is read from the pattern's
                     own stored `meaning` (Prompt 416: "an arbitrary,
                     caller-shaped JSON-safe value") when that value is
                     a dict carrying a "locale" key - reusing the
                     existing flexible field rather than adding a
                     schema migration for one new column. A pattern
                     whose `meaning` carries no "locale" key is
                     locale-agnostic and matches under any requested
                     locale; one that DOES name a locale is only
                     considered when the caller's `locale` argument
                     matches it (or gives none).
    text normalization `understanding.normalization.normalize` (REUSED,
                     the exact same NFKC + whitespace-collapse the
                     Understanding Engine already applies) - so a
                     pattern taught with ordinary spacing matches a
                     message typed with extra/irregular whitespace,
                     without this module inventing a second
                     normalization step.
    tokenization     none of its own: matching works at the level of
                     whitespace-separated runs of the (already
                     normalized) text plus one small, fixed, anchored
                     regex compiled per pattern (see `_compile_pattern`
                     below) - deterministic structural matching, not a
                     parser and not a model.

What a learned pattern's `key` (Prompt 416: "the learned text, verbatim
... a sentence-pattern template") looks like here: ordinary literal
words, plus zero or more variable placeholders written `{{name}}`
(e.g. "من {{X}} را دوست دارم", "I love {{thing}}"), or the anonymous
placeholder `___` (three or more underscores - the exact convention
`language_learning_store.py`'s own docstring already illustrates,
"___ is a ___"), auto-named `var_1`, `var_2`, ... in left-to-right
order. Nothing about `LanguageLearningStore.learn_item()` itself
changes: a pattern is taught exactly the same way any other item is
(`learn_item(language, ITEM_TYPE_PATTERN, "من {{X}} را دوست دارم",
meaning={...})`) - this module only reads what was taught.

Matching, precisely (bounded and deterministic - see the constants
below for the exact bounds):

    1. The message is normalized (REUSED, see above) and, when it is
       empty after normalization, no pattern is even considered
       (NOT_FOUND, `REASON_EMPTY_MESSAGE`).
    2. Candidate patterns are read via `items_for_language()` - narrowed
       to `language` when given (never matching a learned pattern of an
       unrelated language against a message asked in another one), or,
       when `language` is None, gathered across every language that has
       at least one learned item (`languages()`), each still carrying
       its own `language` - never merged into one pool. Reading is
       capped at `max_patterns` (default `DEFAULT_MAX_PATTERNS`, hard
       cap `MAX_PATTERNS_LIMIT`) so this stage's cost never depends on
       how many patterns have been taught; `truncated` reports when the
       cap actually cut something off.
    3. `locale`, when given, additionally filters out any candidate
       pattern whose own stored locale (see above) is set and differs.
    4. Each remaining candidate's template is compiled (see
       `_compile_pattern`) into one small, fixed, anchored regex - every
       literal word must match exactly (case/format-insensitively for
       scripts that have a notion of case; a no-op for Persian), and
       each `{{name}}` placeholder captures one or more words,
       non-greedily, bounded by the literal words around it. This is
       the "deterministic structural matching" the spec calls for:
       there is no scoring, no fuzzy comparison, and no embedding
       anywhere in this module.
    5. A template with two variable placeholders directly adjacent (no
       literal word between them) has a boundary between those two
       variables that is NOT structurally determined by anything the
       system was taught - accepting the first split a regex engine
       happens to try would be exactly the kind of guess this module
       must never make. Such a pattern is marked `indeterminate` at
       compile time and, if it is the only kind of candidate whose
       literal skeleton matches the message, the result is
       `STATUS_NOT_RESOLVED` (never guessed at, never silently
       resolved) - see requirement 4's "insufficient to determine a
       match".
    6. Zero candidates match at all -> `STATUS_NOT_FOUND`.
       Exactly one candidate matches (and is determinate) ->
       `STATUS_MATCHED`, with `matched_pattern_id`, `matched_pattern_text`
       and every extracted `variables` value populated, plus the
       pattern's own stored `meaning`, `confidence` and `source` -
       exactly what was taught, never anything inferred.
       More than one DIFFERENT learned pattern matches the same message
       equally -> `STATUS_AMBIGUOUS`, with every match kept in
       `candidates` and no meaning ever picked among them by guessing.

This module never writes to the learning store, memory, knowledge or
conversation state - it is a pure, read-only, bounded lookup, exactly
like `meaning_resolution.MeaningResolver` before it.

Integration (Prompt 421's own requirement 5): connected to the existing
Understanding Engine the same way Prompt 419/420 connected the meaning
resolver/disambiguator - see `deterministic_fallback_backend.py`'s
optional `pattern_matcher` constructor argument and
`language_understanding_result.py`'s `learned_pattern_match` field.
Nothing about the Understanding Engine, the parser, or any existing
result is redesigned or replaced by this stage.

Prompt 422 builds on this module (learned_sentence_structure.py reports
the ordered fixed/variable components of a MATCHED message) and reuses
`_split_template`, `_literal_regex` and `_VARIABLE_CAPTURE` from here so
there is exactly one definition of what a variable is. Nothing about
matching itself changed: `_compile_pattern` produces the identical regex.
"""

import re

from understanding.normalization import normalize

from .language_learning_store import ITEM_TYPE_PATTERN, _resolve_language

STATUS_MATCHED = "MATCHED"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_NOT_RESOLVED = "NOT_RESOLVED"
ALL_STATUSES = (STATUS_MATCHED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS, STATUS_NOT_RESOLVED)

REASON_EMPTY_MESSAGE = "empty_message"
REASON_NO_PATTERN_MATCHED = "no_learned_pattern_matched_message_structure"
REASON_SINGLE_PATTERN_MATCHED = "single_learned_pattern_matched"
REASON_MULTIPLE_PATTERNS_MATCHED = "multiple_learned_patterns_matched_equally"
REASON_INDETERMINATE_STRUCTURE = "indeterminate_variable_boundary"
# Prompt 438: the message matched no learned pattern's structure
# directly, but an explicit, already-stored relationship (see
# learned_expression_variation_matcher.py) connects it to one -
# variable-free (literal) learned patterns only; see LearnedPatternMatcher.
REASON_SINGLE_PATTERN_MATCHED_VIA_VARIATION = "single_learned_pattern_matched_via_variation"
REASON_MULTIPLE_PATTERNS_MATCHED_VIA_VARIATION = "multiple_learned_patterns_matched_via_variation"

# Small, fixed bounds - same spirit as meaning_resolution.py's own
# MAX_MATCHED_ITEMS: keeps this stage's cost independent of how many
# sentence patterns have been taught, without a caller needing to
# think about it on every call.
DEFAULT_MAX_PATTERNS = 50
MAX_PATTERNS_LIMIT = 200

# {{name}} - a named placeholder - or a run of 3+ underscores, the
# anonymous placeholder `language_learning_store.py`'s own docstring
# already illustrates ("___ is a ___").
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}|_{3,}")

# The one regex fragment a variable placeholder compiles to: non-greedy,
# at least one non-blank character. Shared (Prompt 422) with
# learned_sentence_structure.py so structural extraction is computed
# from the EXACT same variable semantics this matcher used to decide the
# match - never a second, subtly different variable definition.
_VARIABLE_BODY = r"\S.*?|\S"
_VARIABLE_CAPTURE = "(" + _VARIABLE_BODY + ")"


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bounded(value, name, default, hard_cap):
    """None -> default; otherwise a non-negative int, clamped to the
    hard cap. Anything else is a caller error - same convention as
    meaning_resolution.py's own `_bounded`."""
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int or None")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return min(value, hard_cap)


def _normalized_text(text):
    if text is None:
        text = ""
    elif not isinstance(text, str):
        text = str(text)
    return normalize(text).normalized_text


def _split_template(template):
    """Split a learned pattern's `key` into an ordered list of
    ("literal", text) / ("var", name) segments. Purely structural -
    never interprets, validates, or rewrites the template text itself
    beyond splitting on the placeholder markers."""
    segments = []
    pos = 0
    anon_index = 0
    for match in _PLACEHOLDER_RE.finditer(template):
        if match.start() > pos:
            literal = template[pos:match.start()]
            if literal.strip():
                segments.append(("literal", literal))
        name = match.group(1)
        if not name:
            anon_index += 1
            name = f"var_{anon_index}"
        segments.append(("var", name))
        pos = match.end()
    if pos < len(template):
        literal = template[pos:]
        if literal.strip():
            segments.append(("literal", literal))
    return segments


def _literal_regex(words):
    """Regex for a literal run of already-split words: every word must
    match exactly, joined by any whitespace. Shared with
    learned_sentence_structure.py (Prompt 422) - see `_VARIABLE_BODY`."""
    return r"\s+".join(re.escape(word) for word in words)


def _compile_pattern(segments):
    """Compile a pattern's segments (see `_split_template`) into one
    small, fixed, anchored regex. Returns (compiled_regex, var_names,
    indeterminate) - `indeterminate` is True when two variables sit
    directly adjacent with no literal word between them, so their
    shared boundary cannot be determined structurally (see the module
    docstring's step 5). Deterministic and bounded: exactly one regex,
    built once, from exactly the segments already extracted - no
    recursive search, no backtracking beyond ordinary regex evaluation
    of one small, fixed expression."""
    parts = []
    var_names = []
    indeterminate = False
    prev_was_var = False
    for kind, value in segments:
        if kind == "literal":
            words = value.split()
            if not words:
                continue
            parts.append(_literal_regex(words))
            prev_was_var = False
        else:
            if prev_was_var:
                indeterminate = True
            var_names.append(value)
            # Non-greedy, but each variable must capture at least one
            # non-blank character - an empty variable value is never
            # accepted as a match.
            parts.append(_VARIABLE_CAPTURE)
            prev_was_var = True
    if not parts:
        return re.compile(r"^\s*$"), [], False
    pattern_re = r"^\s*" + r"\s+".join(parts) + r"\s*$"
    return re.compile(pattern_re, re.IGNORECASE | re.UNICODE), var_names, indeterminate


def _pattern_locale(item):
    meaning = item.get("meaning")
    if isinstance(meaning, dict):
        return meaning.get("locale")
    return None


def _locale_matches(item, locale):
    if locale is None:
        return True
    pattern_locale = _pattern_locale(item)
    return pattern_locale is None or pattern_locale == locale


def _pattern_identity(item, variables=None):
    identity = {
        "pattern_id": item["id"], "language": item["language"],
        "pattern_text": item["key"], "meaning": item.get("meaning"),
    }
    if variables is not None:
        identity["variables"] = variables
    return identity


class LearnedPatternMatchResult:
    """Plain, JSON-shaped result - same `to_dict()` convention used
    throughout this package. Never constructed by a caller;
    `LearnedPatternMatcher.match()` returns these.

        original_message   the message exactly as given, verbatim -
                            never normalized, rewritten, or translated.
        status              one of ALL_STATUSES above.
        matched             True exactly when status == STATUS_MATCHED.
        matched_pattern_id  the id of the one learned pattern this
                            message was recognized as an instance of,
                            or None.
        matched_pattern_text  that pattern's own `key`, verbatim, or
                            None.
        variables           {name: extracted text} for the matched
                            pattern, or {} when not MATCHED.
        meaning             the matched pattern's own stored `meaning`
                            (Prompt 416; whatever a caller taught it to
                            be - never invented here), or None.
        language            the language actually matched under
                            (the matched pattern's own `language`, or
                            the `language` this call was given), or
                            None.
        locale              the `locale` this call was given, or None.
        confidence          the matched pattern's own stored
                            `confidence` (Prompt 416), or None.
        source              the matched pattern's own stored `source`
                            (Prompt 416), or None.
        candidates          every learned pattern this call found
                            structurally relevant when status is
                            AMBIGUOUS or NOT_RESOLVED - never collapsed,
                            never guessed at; [] otherwise.
        reason              one of the REASON_* constants above.
        truncated           True when `max_patterns` cut off a learned
                            pattern that might otherwise have been
                            considered.
        limits              the bounds actually applied.
    """

    def __init__(self, original_message, status, matched_pattern_id, matched_pattern_text,
                 variables, meaning, language, locale, confidence, source, candidates, reason,
                 truncated, limits):
        self.original_message = original_message
        self.status = status
        self.matched_pattern_id = matched_pattern_id
        self.matched_pattern_text = matched_pattern_text
        self.variables = variables
        self.meaning = meaning
        self.language = language
        self.locale = locale
        self.confidence = confidence
        self.source = source
        self.candidates = candidates
        self.reason = reason
        self.truncated = truncated
        self.limits = limits

    @property
    def matched(self):
        return self.status == STATUS_MATCHED

    def __repr__(self):
        return (
            f"LearnedPatternMatchResult(status={self.status!r}, "
            f"matched_pattern_id={self.matched_pattern_id!r}, reason={self.reason!r})"
        )

    def to_dict(self):
        return {
            "original_message": self.original_message,
            "status": self.status,
            "matched": self.matched,
            "matched_pattern_id": self.matched_pattern_id,
            "matched_pattern_text": self.matched_pattern_text,
            "variables": dict(self.variables) if self.variables else {},
            "meaning": self.meaning,
            "language": self.language,
            "locale": self.locale,
            "confidence": self.confidence,
            "source": self.source,
            "candidates": list(self.candidates) if self.candidates else [],
            "reason": self.reason,
            "truncated": self.truncated,
            "limits": dict(self.limits),
        }


class LearnedPatternMatcher:
    """Composes an existing `LanguageLearningStore` (Prompt 416) - owns
    no storage of its own and writes nothing. Every call is a
    deterministic, bounded read. Stateless: safe to reuse one instance
    for every call, same convention as `MeaningResolver`.

    `variation_matcher` (Prompt 438, optional): a
    `LearnedExpressionVariationMatcher` (learned_expression_variation_matcher.py).
    Left as None (the default), behaviour is IDENTICAL to before Prompt
    438 - purely additive. When given, `match()` consults it ONLY as a
    fallback, after the existing structural matching finds no candidate
    at all (never in place of, and never before, the existing
    exact/structural matching - see that module's own docstring: "do
    not replace the existing exact-expression matching") - and only for
    a candidate pattern with NO variable placeholders (a whole learned
    pattern's literal text is itself the "expression" being varied;
    extracting variables through a variation is out of this stage's
    scope)."""

    def __init__(self, language_learning, variation_matcher=None):
        self.language_learning = language_learning
        self.variation_matcher = variation_matcher

    def match(self, message, language=None, locale=None, max_patterns=None):
        """Recognize `message` as an instance of a previously learned
        sentence pattern, or report why it could not be. `language`
        narrows the search to one language/locale family (canonicalized
        the same way every other lookup in this package is); left as
        None, every language with at least one learned pattern is
        searched, each candidate still carrying its own `language`.
        `locale`, when given, additionally excludes a candidate pattern
        that names a different locale in its own stored `meaning` (see
        the module docstring) - it never excludes a locale-agnostic
        pattern. `max_patterns` bounds how many learned patterns are
        even read (see DEFAULT_MAX_PATTERNS / MAX_PATTERNS_LIMIT).

        Returns a `LearnedPatternMatchResult`. Never guesses: a message
        this system was never taught a matching structure for is
        NOT_FOUND, several equally-plausible learned patterns is
        AMBIGUOUS, and a structurally underdetermined match (see the
        module docstring's step 5) is NOT_RESOLVED - MATCHED is
        returned only when exactly one already-learned pattern's
        literal structure lines up with `message` and every one of its
        variables has an unambiguous boundary."""
        max_patterns = _bounded(max_patterns, "max_patterns", DEFAULT_MAX_PATTERNS,
                                 MAX_PATTERNS_LIMIT)
        limits = {"max_patterns": max_patterns}
        original_message = message if isinstance(message, str) else (
            "" if message is None else str(message)
        )
        normalized_message = _normalized_text(original_message)

        if not normalized_message:
            return LearnedPatternMatchResult(
                original_message, STATUS_NOT_FOUND, None, None, {}, None, language, locale,
                None, None, [], REASON_EMPTY_MESSAGE, False, limits,
            )

        candidates, truncated = self._collect_patterns(language, max_patterns)

        matches = []
        indeterminate_hits = []
        for item in candidates:
            if not _locale_matches(item, locale):
                continue
            segments = _split_template(item["key"])
            regex, var_names, indeterminate = _compile_pattern(segments)
            found = regex.match(normalized_message)
            if not found:
                continue
            if indeterminate:
                indeterminate_hits.append(item)
                continue
            variables = {
                name: (found.group(index + 1) or "").strip()
                for index, name in enumerate(var_names)
            }
            matches.append((item, variables))

        if len(matches) == 1:
            item, variables = matches[0]
            return LearnedPatternMatchResult(
                original_message, STATUS_MATCHED, item["id"], item["key"], variables,
                item.get("meaning"), item["language"], locale, item.get("confidence"),
                item.get("source"), [], REASON_SINGLE_PATTERN_MATCHED, truncated, limits,
            )

        if len(matches) > 1:
            candidate_identities = [_pattern_identity(item, vars_) for item, vars_ in matches]
            return LearnedPatternMatchResult(
                original_message, STATUS_AMBIGUOUS, None, None, {}, None, language, locale,
                None, None, candidate_identities, REASON_MULTIPLE_PATTERNS_MATCHED, truncated,
                limits,
            )

        if indeterminate_hits:
            candidate_identities = [_pattern_identity(item) for item in indeterminate_hits]
            return LearnedPatternMatchResult(
                original_message, STATUS_NOT_RESOLVED, None, None, {}, None, language, locale,
                None, None, candidate_identities, REASON_INDETERMINATE_STRUCTURE, truncated,
                limits,
            )

        if self.variation_matcher is not None:
            # Prompt 438 fallback: no learned pattern's STRUCTURE lined
            # up with `message` directly - see whether an explicit,
            # already-stored relationship connects the message text to
            # a literal (variable-free) learned pattern. Never
            # consulted before, and never in place of, the structural
            # matching above.
            variation_result = self.variation_matcher.match(
                normalized_message, language=language, item_type=ITEM_TYPE_PATTERN, locale=locale,
            )
            literal_matches = []
            for candidate in variation_result.candidates:
                segments = _split_template(candidate["matched_expression"])
                if any(kind == "var" for kind, _ in segments):
                    continue  # out of scope: variable extraction via a variation
                item = self.language_learning.get_item(
                    candidate["language"], ITEM_TYPE_PATTERN, candidate["matched_expression"],
                )
                if item is not None:
                    literal_matches.append(item)

            if len(literal_matches) == 1:
                item = literal_matches[0]
                return LearnedPatternMatchResult(
                    original_message, STATUS_MATCHED, item["id"], item["key"], {},
                    item.get("meaning"), item["language"], locale, item.get("confidence"),
                    item.get("source"), [], REASON_SINGLE_PATTERN_MATCHED_VIA_VARIATION,
                    truncated or variation_result.truncated, limits,
                )
            if len(literal_matches) > 1:
                candidate_identities = [_pattern_identity(item) for item in literal_matches]
                return LearnedPatternMatchResult(
                    original_message, STATUS_AMBIGUOUS, None, None, {}, None, language, locale,
                    None, None, candidate_identities, REASON_MULTIPLE_PATTERNS_MATCHED_VIA_VARIATION,
                    truncated or variation_result.truncated, limits,
                )

        return LearnedPatternMatchResult(
            original_message, STATUS_NOT_FOUND, None, None, {}, None, language, locale, None,
            None, [], REASON_NO_PATTERN_MATCHED, truncated, limits,
        )

    # ------------------------------------------------------------------
    def _collect_patterns(self, language, max_patterns):
        """Bounded, deterministic read of every candidate learned
        pattern - see the module docstring's step 2. Returns
        (items, truncated). Read-only: a single `items_for_language()`
        call per language considered, never one per pattern."""
        if language is not None:
            language = _resolve_language(language)
            items = self.language_learning.items_for_language(
                language, item_type=ITEM_TYPE_PATTERN,
            )
            return items[:max_patterns], len(items) > max_patterns

        items = []
        truncated = False
        for one_language in self.language_learning.languages():
            remaining = max_patterns - len(items)
            language_items = self.language_learning.items_for_language(
                one_language, item_type=ITEM_TYPE_PATTERN,
            )
            if not language_items:
                continue
            if remaining <= 0:
                truncated = True
                continue
            if len(language_items) > remaining:
                truncated = True
            items.extend(language_items[:remaining])
        return items, truncated
