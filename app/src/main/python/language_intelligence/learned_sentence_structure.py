"""
Language Intelligence - Learned Sentence Structure Extraction
===================================================================
Prompt 422. When a message matches a learned sentence pattern (Prompt
421, `learned_pattern_matching.LearnedPatternMatcher`), report the
message's *structure* as that pattern defines it: an ordered list of
components, each either a FIXED part of the pattern (its literal words)
or a VARIABLE part (a named placeholder and the value the message
supplied for it), together with where each one sits in the message.

Example - the learned pattern "من {{X}} را به {{Y}} می‌دهم" and the
message "من کتاب را به علی می‌دهم" give, in pattern order:

    0  fixed     "من"
    1  variable  X = "کتاب"
    2  fixed     "را به"
    3  variable  Y = "علی"      (kept separate from X)
    4  fixed     "می‌دهم"

This is NOT grammar analysis. The only "roles" this module can report
are the two the learned pattern itself already defines - "literal words
the pattern requires" and "named variable slot". It never labels a word
a noun/verb/subject/object, never infers a role the pattern did not
state, and never guesses a meaning - the only meaning ever attached is
the one already stored on the matched pattern (Prompt 416).

Reuse map (this stage adds no matching, no storage, no new intelligence):

    pattern matching  `LearnedPatternMatcher.match()` (Prompt 421) -
                      REUSED, never re-implemented. `extract()` below
                      simply calls it; `from_match()` takes a match
                      result the caller ALREADY has (the Understanding
                      Engine integration does exactly that, so a message
                      is matched once, not twice). Which pattern matched,
                      whether the match is MATCHED / NOT_FOUND /
                      AMBIGUOUS / NOT_RESOLVED, the variable values, the
                      meaning, language, confidence and source are all
                      taken from that result unchanged.
    template parsing  `learned_pattern_matching._split_template()` and
                      the shared regex fragments `_literal_regex()` /
                      `_VARIABLE_CAPTURE` (Prompt 422 pulled the latter
                      two out of the 421 module so this module compiles
                      variables with the EXACT same semantics the matcher
                      used to decide the match - one definition of "a
                      variable", not two).
    normalization     `understanding.normalization.normalize` via the
                      matcher's own `_normalized_text` - offsets below
                      refer to that normalized text.
    statuses/reasons  the 421 STATUS_* / REASON_* constants, reused as-is.

What the only extra work here is: matching is already decided, so this
module recompiles the matched pattern's own template into one anchored
regex with one capture group per *component* (instead of per variable)
and reads the spans back. It then cross-checks the variable values it
read against the values the matcher reported; if they ever disagree,
nothing is reported (see REASON_STRUCTURE_MISMATCH) rather than
choosing one silently.

Statuses (same vocabulary as Prompt 421 - nothing new to learn):

    MATCHED        exactly one learned pattern matched and every
                   component's boundary is determined by the pattern:
                   `components` is the complete ordered structure.
    NOT_FOUND      no learned pattern matched (empty message, unknown
                   structure, language or locale mismatch). No
                   components.
    AMBIGUOUS      several different learned patterns matched equally.
                   No components: picking one structure among them
                   would be a guess. Every candidate (with its own
                   variables) is preserved in `candidates`.
    NOT_RESOLVED   the pattern's structure cannot be fully determined -
                   today, exactly the case Prompt 421 already reports:
                   two variables directly adjacent with no literal word
                   between them, so the boundary between them is not
                   defined by anything that was taught. When exactly one
                   learned pattern lines up with the message, its
                   determined parts (fixed components and isolated
                   variables) are still reported and the adjacent
                   variables are reported as ONE `unresolved` component
                   holding the exact text they cover, with their names -
                   the portion is preserved, no split is invented, and
                   no meaning is attached. With several candidates, no
                   components at all (`candidates` keeps them).

Component kinds:

    fixed          literal words of the pattern. `text` is what the
                   message contains; `pattern_segment` is the literal as
                   it was taught (they differ only by letter case for
                   scripts that have case).
    variable       one named placeholder. `variable_name` and `value`
                   (== `text`).
    unresolved     a run of adjacent placeholders whose boundaries are
                   not defined. `variable_names` lists them in order;
                   `text` is the whole run, unsplit; `variable_name` and
                   `value` are None.

`start` / `end` are half-open character offsets (Python string indices,
i.e. Unicode code points) into `normalized_message`. `position` is the
component's 0-based order within the pattern.

Language safety: no language-specific rule exists in this module. The
structure comes only from the learned pattern's own template, so any
language the Language Learning Store (Prompt 416) can hold a pattern
for works identically; Persian text (including ZWNJ, e.g. "می‌دهم") is
handled as ordinary Unicode, exactly as in Prompt 421. `language` is the
matched pattern's own language; `locale` is the pattern's own stored
locale when it names one (see learned_pattern_matching.py), otherwise
the locale the call was given.

Like the matcher, this module is pure, deterministic, read-only and
bounded: it writes to no store and adds no state.
"""

import re

from .learned_pattern_matching import (
    STATUS_MATCHED, STATUS_NOT_RESOLVED, REASON_INDETERMINATE_STRUCTURE,
    _VARIABLE_BODY, _VARIABLE_CAPTURE, _literal_regex, _split_template, _normalized_text,
    _pattern_locale,
)

COMPONENT_FIXED = "fixed"
COMPONENT_VARIABLE = "variable"
COMPONENT_UNRESOLVED = "unresolved"
ALL_COMPONENT_KINDS = (COMPONENT_FIXED, COMPONENT_VARIABLE, COMPONENT_UNRESOLVED)

# Reasons - a MATCHED structure gets the first; the second is the
# defensive cross-check described in the module docstring. Every other
# status keeps the reason Prompt 421's matcher already gave (REUSED).
REASON_STRUCTURE_EXTRACTED = "structure_extracted_from_learned_pattern"
REASON_STRUCTURE_MISMATCH = "structure_disagrees_with_pattern_match"

_UNRESOLVED_VARIABLE = "(?:" + _VARIABLE_BODY + ")"


def _group_components(segments):
    """Turn `_split_template()` segments into ordered structural
    components. A run of two or more adjacent variables becomes a single
    `unresolved` component - the pattern does not define where one ends
    and the next begins, so this module never splits it."""
    components = []
    for kind, value in segments:
        if kind == "literal":
            words = value.split()
            if not words:
                continue
            components.append({"kind": COMPONENT_FIXED, "words": words})
            continue
        last = components[-1] if components else None
        if last is not None and last["kind"] in (COMPONENT_VARIABLE, COMPONENT_UNRESOLVED):
            last["kind"] = COMPONENT_UNRESOLVED
            last["names"].append(value)
        else:
            components.append({"kind": COMPONENT_VARIABLE, "names": [value]})
    return components


def _compile_components(components):
    """One anchored regex, exactly one capture group per component and
    in component order - so group `i + 1` is `components[i]`. Built from
    the same fragments `learned_pattern_matching._compile_pattern` uses."""
    parts = []
    for component in components:
        if component["kind"] == COMPONENT_FIXED:
            parts.append("(" + _literal_regex(component["words"]) + ")")
        elif component["kind"] == COMPONENT_VARIABLE:
            parts.append(_VARIABLE_CAPTURE)
        else:
            run = r"\s+".join(_UNRESOLVED_VARIABLE for _ in component["names"])
            parts.append("(" + run + ")")
    return re.compile(r"^\s*" + r"\s+".join(parts) + r"\s*$", re.IGNORECASE | re.UNICODE)


def _build_components(pattern_text, normalized_message):
    """Locate every component of `pattern_text` in `normalized_message`.
    Returns the ordered component dicts, or None when the template does
    not line up with the message (which, for a pattern the matcher has
    already matched, is never expected)."""
    components = _group_components(_split_template(pattern_text))
    if not components:
        return None
    found = _compile_components(components).match(normalized_message)
    if not found:
        return None
    built = []
    for index, component in enumerate(components):
        text = found.group(index + 1)
        start, end = found.span(index + 1)
        kind = component["kind"]
        built.append({
            "position": index,
            "kind": kind,
            "text": text,
            "start": start,
            "end": end,
            "pattern_segment": " ".join(component["words"]) if kind == COMPONENT_FIXED else None,
            "variable_name": component["names"][0] if kind == COMPONENT_VARIABLE else None,
            "value": text if kind == COMPONENT_VARIABLE else None,
            "variable_names": list(component["names"]) if kind == COMPONENT_UNRESOLVED else [],
        })
    return built


def _variable_values(components):
    """{name: value} in component order - a later component with the
    same name replaces an earlier one, exactly as the matcher's own
    `variables` dict does, so the two are directly comparable."""
    return {
        component["variable_name"]: component["value"]
        for component in components if component["kind"] == COMPONENT_VARIABLE
    }


class LearnedSentenceStructureResult:
    """Plain, JSON-shaped result - same `to_dict()` convention used
    throughout this package. Never constructed by a caller;
    `LearnedSentenceStructureExtractor` returns these.

        original_message      the message exactly as given, verbatim -
                              never normalized, rewritten or translated.
        normalized_message    the text the offsets in `components` refer
                              to (Understanding Engine normalization,
                              REUSED).
        status                one of ALL_STATUSES (Prompt 421's set).
        matched               True exactly when status == STATUS_MATCHED.
        matched_pattern_id    the id of the learned pattern, only when
                              MATCHED (else None) - same as Prompt 421.
        matched_pattern_text  that pattern's own `key`, verbatim, or None.
        components            ordered list of component dicts (see the
                              module docstring: position, kind, text,
                              start, end, pattern_segment, variable_name,
                              value, variable_names). [] unless MATCHED
                              or a single-candidate NOT_RESOLVED.
        meaning               the matched pattern's own stored meaning
                              (Prompt 416), or None - never inferred and
                              never attached to a non-MATCHED result.
        language              the matched pattern's own language (or the
                              language the call was given), or None.
        locale                the matched pattern's own stored locale, or
                              else the locale the call was given, or None.
        confidence, source    the matched pattern's own stored values
                              (Prompt 416), or None.
        candidates            every learned pattern found structurally
                              relevant when AMBIGUOUS / NOT_RESOLVED
                              (Prompt 421's candidate identities,
                              unchanged); [] otherwise.
        reason                a Prompt 421 REASON_* constant, or one of
                              this module's REASON_STRUCTURE_* constants.
        truncated             True when the matcher's `max_patterns` cut
                              off a pattern that might have been
                              considered.
    """

    def __init__(self, original_message, normalized_message, status, matched_pattern_id,
                 matched_pattern_text, components, meaning, language, locale, confidence,
                 source, candidates, reason, truncated):
        self.original_message = original_message
        self.normalized_message = normalized_message
        self.status = status
        self.matched_pattern_id = matched_pattern_id
        self.matched_pattern_text = matched_pattern_text
        self.components = components
        self.meaning = meaning
        self.language = language
        self.locale = locale
        self.confidence = confidence
        self.source = source
        self.candidates = candidates
        self.reason = reason
        self.truncated = truncated

    @property
    def matched(self):
        return self.status == STATUS_MATCHED

    @property
    def variables(self):
        """{variable name: extracted value} for the resolved `variable`
        components - a read-only view of `components`, not extra stored
        data. Unresolved runs contribute nothing."""
        return _variable_values(self.components)

    def __repr__(self):
        return (
            f"LearnedSentenceStructureResult(status={self.status!r}, "
            f"matched_pattern_id={self.matched_pattern_id!r}, "
            f"components={len(self.components)}, reason={self.reason!r})"
        )

    def to_dict(self):
        return {
            "original_message": self.original_message,
            "normalized_message": self.normalized_message,
            "status": self.status,
            "matched": self.matched,
            "matched_pattern_id": self.matched_pattern_id,
            "matched_pattern_text": self.matched_pattern_text,
            "components": [dict(component) for component in self.components],
            "meaning": self.meaning,
            "language": self.language,
            "locale": self.locale,
            "confidence": self.confidence,
            "source": self.source,
            "candidates": list(self.candidates) if self.candidates else [],
            "reason": self.reason,
            "truncated": self.truncated,
        }


class LearnedSentenceStructureExtractor:
    """Composes an existing `LearnedPatternMatcher` (Prompt 421) - owns
    no storage and no pattern matching of its own and writes nothing.
    Stateless: safe to reuse one instance for every call."""

    def __init__(self, pattern_matcher):
        self.pattern_matcher = pattern_matcher

    def extract(self, message, language=None, locale=None, max_patterns=None):
        """Match `message` against the learned sentence patterns (the
        matcher's own `match()`, same arguments) and report its
        structure. Returns a `LearnedSentenceStructureResult`."""
        match = self.pattern_matcher.match(
            message, language=language, locale=locale, max_patterns=max_patterns,
        )
        return self.from_match(match)

    def from_match(self, match, original_message=None):
        """Report the structure for a `LearnedPatternMatchResult` the
        caller already has (no second match is run). `original_message`
        overrides which text is reported as the original - the
        Understanding Engine integration passes the user's untouched
        input here, since the matcher itself is handed the already
        normalized text; offsets always refer to the normalized text
        either way."""
        if original_message is None:
            original_message = match.original_message
        normalized_message = _normalized_text(match.original_message)

        if match.status == STATUS_MATCHED:
            return self._from_matched(match, original_message, normalized_message)
        if match.status == STATUS_NOT_RESOLVED and len(match.candidates or []) == 1:
            return self._from_single_unresolved(match, original_message, normalized_message)
        # NOT_FOUND, AMBIGUOUS, or NOT_RESOLVED with several candidates:
        # nothing to report but why, and the candidates.
        return self._result(match, original_message, normalized_message, match.status, [],
                            reason=match.reason)

    # ------------------------------------------------------------------
    def _from_matched(self, match, original_message, normalized_message):
        components = _build_components(match.matched_pattern_text, normalized_message)
        agrees = (
            components is not None
            and all(c["kind"] != COMPONENT_UNRESOLVED for c in components)
            and _variable_values(components) == match.variables
        )
        if not agrees:
            # Never expected: the matcher and this module read the same
            # template with the same regex fragments. If it ever happens,
            # report that no structure could be determined rather than
            # picking either reading; the pattern involved stays visible
            # in `candidates`.
            involved = [{
                "pattern_id": match.matched_pattern_id, "language": match.language,
                "pattern_text": match.matched_pattern_text, "meaning": match.meaning,
                "variables": dict(match.variables),
            }]
            return self._result(match, original_message, normalized_message,
                                STATUS_NOT_RESOLVED, [], reason=REASON_STRUCTURE_MISMATCH,
                                candidates=involved)
        return self._result(match, original_message, normalized_message, STATUS_MATCHED,
                            components, reason=REASON_STRUCTURE_EXTRACTED)

    def _from_single_unresolved(self, match, original_message, normalized_message):
        candidate = match.candidates[0]
        components = _build_components(candidate["pattern_text"], normalized_message) or []
        # Still NOT_RESOLVED: the adjacent-variable run (if any) is
        # reported unsplit, and no pattern id / meaning is claimed.
        return self._result(match, original_message, normalized_message, STATUS_NOT_RESOLVED,
                            components, reason=REASON_INDETERMINATE_STRUCTURE)

    @staticmethod
    def _result(match, original_message, normalized_message, status, components, reason,
                candidates=None):
        is_match = status == STATUS_MATCHED
        if candidates is None:
            candidates = [] if is_match else list(match.candidates or [])
        locale = match.locale
        if is_match:
            locale = _pattern_locale({"meaning": match.meaning}) or match.locale
        return LearnedSentenceStructureResult(
            original_message=original_message,
            normalized_message=normalized_message,
            status=status,
            matched_pattern_id=match.matched_pattern_id if is_match else None,
            matched_pattern_text=match.matched_pattern_text if is_match else None,
            components=components,
            meaning=match.meaning if is_match else None,
            language=match.language,
            locale=locale,
            confidence=match.confidence if is_match else None,
            source=match.source if is_match else None,
            candidates=candidates,
            reason=reason,
            truncated=match.truncated,
        )
