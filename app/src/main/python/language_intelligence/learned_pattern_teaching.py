"""
Language Intelligence - Learned Sentence Pattern Teaching
===============================================================
Prompt 423. One explicit, deterministic operation for TEACHING a
reusable sentence pattern to the existing language-learning system:

    teacher.teach("fa", "من {{X}} را دوست دارم",
                  meaning={"intent": "likes_thing"}, locale="fa-IR",
                  examples=["من کتاب را دوست دارم"])

This is teaching, not learning. The caller supplies the pattern - its
literal words and its explicitly NAMED variables. Nothing here discovers
a variable in an arbitrary sentence, infers grammar, guesses a meaning,
or writes a pattern the caller did not spell out. A pattern that cannot
be validated is refused whole (STATUS_INVALID) and nothing at all is
stored - validation finishes before the single store write, so there is
no partial state to clean up.

Reuse map (this stage adds no storage, no matcher and no pattern model):

    storage / identity  `LanguageLearningStore.learn_item()` (Prompt 416)
                        with `item_type=ITEM_TYPE_PATTERN` - exactly what
                        Prompts 421/422 already read. A taught pattern IS
                        such an item: same table, same row identity
                        (language, item_type, case/whitespace-normalized
                        key), same learning-event history, same
                        relationships (Prompt 417, keyed by item id).
                        No second pattern table, no second identity rule.
    pattern syntax      Prompt 421's own template representation: literal
                        words plus `{{name}}` placeholders, parsed with
                        its `_PLACEHOLDER_RE` / `_split_template()`. What
                        this module adds is only a stricter GATE in front
                        of that representation (see "Validation").
    recognition         `LearnedPatternMatcher` (Prompt 421) and
                        `LearnedSentenceStructureExtractor` (Prompt 422)
                        are not touched and not wrapped: a taught pattern
                        is found by them the moment it is stored, like
                        any other pattern in the store.
    language            `LanguageLearningStore`'s own `_resolve_language`
                        (canonical_language, Prompt 401) - "fa" and
                        "persian" are one language, an unrecognized code
                        is kept as-is, "" / "unknown" are rejected.
    locale              Prompt 421's existing convention: the store has
                        no locale column, and a pattern's locale is the
                        `"locale"` key of its stored `meaning` object.
                        Teaching writes it there (so 421's locale filter
                        and 422's reported locale work with no change).

Validation (all checked, all reported together, before anything is
written; each is a structured `errors` entry `{"code", "detail"}`):

    empty_pattern / pattern_must_be_text
    malformed_variable_syntax   a stray or unbalanced brace, a single-brace
                                `{X}`, a name Prompt 421 cannot read
                                (`{{1st}}`, `{{a b}}`, `{{نام}}`) - the
                                matcher would silently treat such text as
                                literal words, so it is refused instead
    unnamed_variable            `___` or `{{ }}` or `{{___}}`: teaching
                                requires every variable to be named by
                                the caller, never auto-numbered
    duplicate_variable_name     the pattern model reports ONE value per
                                name (`variables` is a dict), so a repeated
                                name would lose a value; names are
                                case-sensitive (`X` and `x` differ)
    no_fixed_component          a pattern of only variables would match
                                every message in the language
    invalid_language / invalid_locale / locale_language_mismatch /
    locale_conflicts_with_meaning
    invalid_meaning             must be a JSON-safe object (dict) or None
    invalid_confidence          a real, finite number (clamped into
                                [0, 1] exactly as the store does)
    invalid_source / invalid_examples

Non-fatal observations are returned as `warnings` and never block a
teach: adjacent variables (Prompt 421 will report such a pattern's
matches as NOT_RESOLVED - the boundary between them is not defined), a
pattern text that NFKC normalization would change (messages are matched
after NFKC, so such literals could never match), and an example that
does not match the pattern it was supplied with.

Duplicates: the same pattern (same normalized text, same variable names)
for the same language is never stored twice. Teaching it again returns
STATUS_ALREADY_EXISTS. Only metadata the caller explicitly supplies can
change - meaning, confidence, source; new examples are ADDED to the
existing ones (order kept, exact duplicates skipped), never replacing
them - and only if it actually differs. The stored pattern text, its id,
its relationships and everything not supplied are left as they were, and
a re-teach that changes nothing writes nothing. The same text in another
language is a separate pattern. Because the store's identity has no
locale, the same pattern for the same language but a different locale
cannot be a second row: an EXPLICIT locale that differs from the stored
one is reported as STATUS_CONFLICT (nothing changed) instead of silently
re-scoping the existing pattern; leaving `locale` out never conflicts.
The same applies to a stored pattern whose variable NAMES differ only in
letter case (the store folds case in its identity, matching does not).

Originals are preserved: the pattern is stored verbatim as the store's
`key` and every example verbatim (a JSON round trip keeps Persian text
and ZWNJ exactly). Normalization is used only to CHECK an example
against the pattern, never to rewrite what is stored.

Pure Python, no I/O beyond the one `learn_item()` call, no model, no
network, and no Persian- (or any language-) specific rule anywhere.
"""

import json
import math
import re
import unicodedata

from .language_context import canonical_language
from .language_learning_store import ITEM_TYPE_PATTERN, _resolve_language, _clamp_confidence
from .learned_pattern_matching import (
    _PLACEHOLDER_RE, _split_template, _compile_pattern, _normalized_text, _pattern_locale,
)
from .learned_sentence_structure import COMPONENT_FIXED, COMPONENT_VARIABLE

STATUS_CREATED = "CREATED"
STATUS_ALREADY_EXISTS = "ALREADY_EXISTS"
STATUS_INVALID = "INVALID"
STATUS_CONFLICT = "CONFLICT"
ALL_STATUSES = (STATUS_CREATED, STATUS_ALREADY_EXISTS, STATUS_INVALID, STATUS_CONFLICT)

REASON_PATTERN_TAUGHT = "pattern_taught"
REASON_IDENTICAL_PATTERN_EXISTS = "identical_pattern_already_learned"
REASON_LOCALE_DIFFERS = "pattern_exists_with_different_locale"
REASON_VARIABLE_NAMES_DIFFER = "pattern_exists_with_different_variable_names"

ERROR_EMPTY_PATTERN = "empty_pattern"
ERROR_PATTERN_NOT_TEXT = "pattern_must_be_text"
ERROR_MALFORMED_VARIABLE = "malformed_variable_syntax"
ERROR_UNNAMED_VARIABLE = "unnamed_variable"
ERROR_DUPLICATE_VARIABLE = "duplicate_variable_name"
ERROR_NO_FIXED_COMPONENT = "no_fixed_component"
ERROR_INVALID_LANGUAGE = "invalid_language"
ERROR_INVALID_LOCALE = "invalid_locale"
ERROR_LOCALE_LANGUAGE_MISMATCH = "locale_language_mismatch"
ERROR_LOCALE_CONFLICTS_WITH_MEANING = "locale_conflicts_with_meaning"
ERROR_INVALID_MEANING = "invalid_meaning"
ERROR_INVALID_CONFIDENCE = "invalid_confidence"
ERROR_INVALID_SOURCE = "invalid_source"
ERROR_INVALID_EXAMPLES = "invalid_examples"

WARNING_ADJACENT_VARIABLES = "adjacent_variables_boundary_undefined"
WARNING_NOT_NFKC = "pattern_text_not_nfkc_normalized"
WARNING_EXAMPLE_MISMATCH = "example_does_not_match_pattern"

LEARNING_METHOD = "explicit_pattern_teaching"

_EMPTY_VARIABLE_RE = re.compile(r"\{\{\s*\}\}")
_LOCALE_RE = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")


def _issue(code, detail, **extra):
    issue = {"code": code, "detail": detail}
    issue.update(extra)
    return issue


def _is_real_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


# ----------------------------------------------------------------------
# Pattern analysis (pure)
# ----------------------------------------------------------------------
def _analyze_pattern(pattern):
    """Return `(errors, variable_names)` for a candidate pattern text.
    Uses Prompt 421's own placeholder regex, so "valid here" means
    "recognized identically by the matcher"."""
    if not isinstance(pattern, str):
        return [_issue(ERROR_PATTERN_NOT_TEXT, "the pattern must be a string")], []
    if not pattern.strip():
        return [_issue(ERROR_EMPTY_PATTERN, "the pattern is empty")], []

    errors = []
    names = []
    leftover = []
    position = 0
    for match in _PLACEHOLDER_RE.finditer(pattern):
        leftover.append(pattern[position:match.start()])
        leftover.append(" ")
        position = match.end()
        name = match.group(1)
        if name is None or not name.strip("_"):
            errors.append(_issue(
                ERROR_UNNAMED_VARIABLE,
                f"variable at offset {match.start()} has no name; write it as {{{{name}}}}",
                offset=match.start()))
            continue
        names.append(name)
    leftover.append(pattern[position:])
    rest = "".join(leftover)

    for _ in _EMPTY_VARIABLE_RE.finditer(rest):
        errors.append(_issue(
            ERROR_UNNAMED_VARIABLE, "an empty {{ }} placeholder has no name"))
    rest = _EMPTY_VARIABLE_RE.sub(" ", rest)
    if "{" in rest or "}" in rest:
        errors.append(_issue(
            ERROR_MALFORMED_VARIABLE,
            "unbalanced or unreadable braces; a variable is written {{name}} "
            "with a name of letters, digits and underscores that does not start "
            "with a digit"))

    seen = set()
    for name in names:
        if name in seen and not any(
                e["code"] == ERROR_DUPLICATE_VARIABLE and e["variable_name"] == name
                for e in errors):
            errors.append(_issue(
                ERROR_DUPLICATE_VARIABLE,
                f"variable name {name!r} is used more than once", variable_name=name))
        seen.add(name)

    if not errors and not any(kind == "literal" for kind, _ in _split_template(pattern)):
        errors.append(_issue(
            ERROR_NO_FIXED_COMPONENT,
            "a pattern needs at least one literal word besides its variables"))
    return errors, names


def _structure_signature(pattern):
    """What two pattern texts must share to be the same pattern: literal
    words (case- and whitespace-insensitive, as the store's identity and
    the matcher are) and variable names (exact, as the matcher is)."""
    signature = []
    for kind, value in _split_template(pattern):
        if kind == "literal":
            signature.append(("literal", " ".join(value.split()).casefold()))
        else:
            signature.append(("var", value))
    return tuple(signature)


def _template_components(pattern):
    """The taught template as ordered components - fixed literals and
    named variables - using the same kinds Prompt 422 reports."""
    components = []
    for position, (kind, value) in enumerate(_split_template(pattern)):
        if kind == "literal":
            components.append({
                "position": position, "kind": COMPONENT_FIXED,
                "text": " ".join(value.split()), "variable_name": None,
            })
        else:
            components.append({
                "position": position, "kind": COMPONENT_VARIABLE,
                "text": None, "variable_name": value,
            })
    return components


def _pattern_warnings(pattern):
    warnings = []
    segments = _split_template(pattern)
    previous_was_variable = False
    for kind, _ in segments:
        if kind == "var" and previous_was_variable:
            warnings.append(_issue(
                WARNING_ADJACENT_VARIABLES,
                "two variables are adjacent; the boundary between them is not defined, "
                "so matches will be reported NOT_RESOLVED"))
            break
        previous_was_variable = kind == "var"
    if unicodedata.normalize("NFKC", pattern) != pattern:
        warnings.append(_issue(
            WARNING_NOT_NFKC,
            "messages are NFKC-normalized before matching; literal text that NFKC would "
            "change cannot match"))
    return warnings


def _example_warnings(pattern, examples):
    """Advisory only: does each example actually fit the pattern? Uses
    Prompt 421's own compiled regex on normalized text - the matcher's
    own test, not a second one."""
    regex = _compile_pattern(_split_template(pattern))[0]
    return [
        _issue(WARNING_EXAMPLE_MISMATCH, "the example does not match the pattern", index=index)
        for index, example in enumerate(examples)
        if not regex.match(_normalized_text(example))
    ]


def _validate_locale(value, source_name):
    """Return `(locale_or_None, error_or_None)`."""
    if value is None:
        return None, None
    if not isinstance(value, str) or not _LOCALE_RE.fullmatch(value.strip()):
        return None, _issue(
            ERROR_INVALID_LOCALE,
            f"{source_name} must be a locale tag such as 'fa-IR' or 'en-US'")
    return value.strip(), None


def _language_base(value):
    return canonical_language(str(value).strip().lower().replace("_", "-").split("-")[0])


def _dedupe(examples):
    seen, unique = set(), []
    for example in examples:
        if example not in seen:
            seen.add(example)
            unique.append(example)
    return unique


class LearnedPatternTeachingResult:
    """Plain, JSON-shaped result - same `to_dict()` convention used
    throughout this package. Never constructed by a caller;
    `LearnedPatternTeacher.teach()` returns these.

        status            STATUS_CREATED (newly stored), STATUS_ALREADY_EXISTS
                          (the identical pattern was already learned;
                          nothing was duplicated), STATUS_CONFLICT (a
                          pattern with this identity exists but disagrees
                          on locale or variable names; nothing changed) or
                          STATUS_INVALID (refused; nothing stored).
        success           True for CREATED and ALREADY_EXISTS.
        created           True exactly for CREATED.
        already_existed   True for ALREADY_EXISTS and CONFLICT.
        updated_fields    fields of an EXISTING pattern this call changed
                          (subset of "meaning", "confidence", "source",
                          "examples"); [] otherwise.
        pattern_id        the learned item's id (None for INVALID).
        pattern_text      the pattern exactly as stored (the given text
                          for INVALID).
        language          canonical language of the pattern, or None.
        locale            the pattern's locale (stored in `meaning`), or
                          None.
        variables         the variable names, in order, exactly as taught.
        components        the template in order: fixed literals and
                          variables (Prompt 422's kinds).
        meaning           the stored meaning object (includes "locale"
                          when one was taught - Prompt 421's convention).
        confidence, source, examples   as stored.
        warnings          non-fatal observations (never affect status).
        errors            why STATUS_INVALID: `{"code", "detail"}` entries.
        reason            a REASON_* constant, or the first error code.
    """

    def __init__(self, status, reason, pattern_id=None, pattern_text=None, language=None,
                 locale=None, variables=None, components=None, meaning=None, confidence=None,
                 source=None, examples=None, created=False, already_existed=False,
                 updated_fields=None, warnings=None, errors=None):
        self.status = status
        self.reason = reason
        self.pattern_id = pattern_id
        self.pattern_text = pattern_text
        self.language = language
        self.locale = locale
        self.variables = variables if variables is not None else []
        self.components = components if components is not None else []
        self.meaning = meaning
        self.confidence = confidence
        self.source = source
        self.examples = examples if examples is not None else []
        self.created = created
        self.already_existed = already_existed
        self.updated_fields = updated_fields if updated_fields is not None else []
        self.warnings = warnings if warnings is not None else []
        self.errors = errors if errors is not None else []

    @property
    def success(self):
        return self.status in (STATUS_CREATED, STATUS_ALREADY_EXISTS)

    def __repr__(self):
        return (
            f"LearnedPatternTeachingResult(status={self.status!r}, "
            f"pattern_id={self.pattern_id!r}, reason={self.reason!r})"
        )

    def to_dict(self):
        return {
            "status": self.status,
            "success": self.success,
            "created": self.created,
            "already_existed": self.already_existed,
            "updated_fields": list(self.updated_fields),
            "pattern_id": self.pattern_id,
            "pattern_text": self.pattern_text,
            "language": self.language,
            "locale": self.locale,
            "variables": list(self.variables),
            "components": [dict(component) for component in self.components],
            "meaning": self.meaning,
            "confidence": self.confidence,
            "source": self.source,
            "examples": list(self.examples),
            "warnings": [dict(w) for w in self.warnings],
            "errors": [dict(e) for e in self.errors],
            "reason": self.reason,
        }


class LearnedPatternTeacher:
    """Composes an existing `LanguageLearningStore` (Prompt 416) - owns no
    storage and no pattern representation of its own. Stateless: safe to
    reuse one instance for every call."""

    def __init__(self, language_learning):
        self.language_learning = language_learning

    def teach(self, language, pattern, locale=None, meaning=None, confidence=None, source=None,
              examples=None):
        """Teach the sentence `pattern` for `language`. See the module
        docstring for validation, duplicate and locale rules. Returns a
        `LearnedPatternTeachingResult`; never raises for bad input."""
        errors = []

        resolved_language = None
        try:
            resolved_language = _resolve_language(language)
        except (ValueError, TypeError) as error:
            errors.append(_issue(ERROR_INVALID_LANGUAGE, str(error)))

        pattern_errors, names = _analyze_pattern(pattern)
        errors.extend(pattern_errors)

        explicit_locale, error = _validate_locale(locale, "locale")
        if error:
            errors.append(error)
        meaning_locale = None
        meaning_ok = meaning is None or isinstance(meaning, dict)
        if not meaning_ok:
            errors.append(_issue(ERROR_INVALID_MEANING,
                                 "meaning must be an object (dict) or None"))
        elif meaning:
            try:
                json.dumps(meaning)
            except (TypeError, ValueError) as json_error:
                meaning_ok = False
                errors.append(_issue(ERROR_INVALID_MEANING,
                                     f"meaning must be JSON-safe: {json_error}"))
            if meaning_ok and "locale" in meaning:
                meaning_locale, error = _validate_locale(meaning["locale"], "meaning['locale']")
                if error:
                    errors.append(error)
        if explicit_locale and meaning_locale and explicit_locale != meaning_locale:
            errors.append(_issue(
                ERROR_LOCALE_CONFLICTS_WITH_MEANING,
                "locale and meaning['locale'] name different locales"))
        effective_locale = explicit_locale or meaning_locale
        if effective_locale and resolved_language is not None:
            if _language_base(effective_locale) != _language_base(language):
                errors.append(_issue(
                    ERROR_LOCALE_LANGUAGE_MISMATCH,
                    f"locale {effective_locale!r} does not belong to language {language!r}"))

        if confidence is not None and not _is_real_number(confidence):
            errors.append(_issue(ERROR_INVALID_CONFIDENCE,
                                 "confidence must be a finite number or None"))
        if source is not None and (not isinstance(source, str) or not source.strip()):
            errors.append(_issue(ERROR_INVALID_SOURCE, "source must be a non-empty string or None"))

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

        if errors:
            return LearnedPatternTeachingResult(
                STATUS_INVALID, errors[0]["code"], pattern_text=pattern if isinstance(pattern, str) else None,
                language=resolved_language, errors=errors,
            )

        clamped_confidence = _clamp_confidence(confidence)
        existing = self.language_learning.get_item(resolved_language, ITEM_TYPE_PATTERN, pattern)
        if existing is None:
            return self._create(resolved_language, pattern, effective_locale, meaning,
                                clamped_confidence, source, example_list)
        return self._existing(existing, pattern, effective_locale, meaning,
                              clamped_confidence, source, example_list)

    # ------------------------------------------------------------------
    def _create(self, language, pattern, locale, meaning, confidence, source, examples):
        stored_meaning = meaning
        if locale is not None:
            stored_meaning = dict(meaning or {})
            stored_meaning["locale"] = locale
        item = self.language_learning.learn_item(
            language, ITEM_TYPE_PATTERN, pattern, meaning=stored_meaning,
            examples=examples or None, confidence=confidence, source=source,
            learning_method=LEARNING_METHOD,
        )
        warnings = _pattern_warnings(item["key"]) + _example_warnings(item["key"], examples)
        return self._result(item, STATUS_CREATED, REASON_PATTERN_TAUGHT, created=True,
                            warnings=warnings)

    def _existing(self, existing, pattern, taught_locale, meaning, confidence, source,
                  examples):
        stored_locale = _pattern_locale(existing)
        if _structure_signature(existing["key"]) != _structure_signature(pattern):
            return self._result(existing, STATUS_CONFLICT, REASON_VARIABLE_NAMES_DIFFER,
                                already_existed=True, errors=[_issue(
                                    REASON_VARIABLE_NAMES_DIFFER,
                                    f"the stored pattern {existing['key']!r} has variable names "
                                    "that differ (in letter case) from the ones taught")])
        if taught_locale is not None and taught_locale != stored_locale:
            return self._result(existing, STATUS_CONFLICT, REASON_LOCALE_DIFFERS,
                                already_existed=True, errors=[_issue(
                                    REASON_LOCALE_DIFFERS,
                                    f"the stored pattern has locale {stored_locale!r}; "
                                    f"{taught_locale!r} was taught")])

        changes = {}
        updated = []
        if meaning is not None:
            new_meaning = dict(meaning)
            if stored_locale is not None:
                new_meaning["locale"] = stored_locale
            if new_meaning != existing["meaning"]:
                changes["meaning"] = new_meaning
                updated.append("meaning")
        if confidence is not None and confidence != existing["confidence"]:
            changes["confidence"] = confidence
            updated.append("confidence")
        if source is not None and source != existing["source"]:
            changes["source"] = source
            updated.append("source")
        added_examples = [e for e in examples if e not in existing["examples"]]
        if added_examples:
            changes["examples"] = list(existing["examples"]) + added_examples
            updated.append("examples")

        item = existing
        if changes:
            # Pass the STORED key so the pattern text is never rewritten,
            # and no `relationships` / `learning_method` so they are kept.
            item = self.language_learning.learn_item(
                existing["language"], ITEM_TYPE_PATTERN, existing["key"], **changes)
        warnings = _pattern_warnings(item["key"]) + _example_warnings(item["key"], added_examples)
        return self._result(item, STATUS_ALREADY_EXISTS, REASON_IDENTICAL_PATTERN_EXISTS,
                            already_existed=True, updated_fields=updated, warnings=warnings)

    @staticmethod
    def _result(item, status, reason, created=False, already_existed=False, updated_fields=None,
                warnings=None, errors=None):
        components = _template_components(item["key"])
        return LearnedPatternTeachingResult(
            status=status, reason=reason, pattern_id=item["id"], pattern_text=item["key"],
            language=item["language"], locale=_pattern_locale(item),
            variables=[c["variable_name"] for c in components if c["kind"] == COMPONENT_VARIABLE],
            components=components, meaning=item["meaning"], confidence=item["confidence"],
            source=item["source"], examples=list(item["examples"]), created=created,
            already_existed=already_existed, updated_fields=updated_fields, warnings=warnings,
            errors=errors,
        )
