"""
Language Intelligence - Learned Response Pattern Selection
================================================================
Prompt 434. One focused capability: from the learned-language
information the response-generation path ALREADY has, select the one
learned response pattern that applies - or say plainly that none does,
or that several do equally:

    LanguageUnderstandingResult                   (Prompt 397-424)
      -> ResponsePlan                             (response_planning.py, 425)
      -> LearnedLanguageGuidance                  (language_guidance.py, 433)
      -> LearnedResponsePatternSelection          (this module, 434)
      -> ResponseGenerationContext.response_pattern_selection
         (response_generation_context.py)
      -> BackendGenerationRequest.response_pattern_selection
         (response_generation_request.py)
      -> existing response generation

This module generates NO response text, stores NOTHING, learns NOTHING
and reads NO store. `LearnedResponsePatternSelector.select()` is a pure
function of the plan/context dict and the guidance it is handed.

What a "learned response pattern" is here (no new storage)
------------------------------------------------------------
The language-learning system (Prompt 416-424) already stores an OPEN,
caller-shaped `meaning` value on every learned item, and Prompt 425's
`response_action` is already read out of exactly that value (a taught
meaning's `{"response_action": "greet"}`, or a taught sentence
pattern's `meaning={...}`). A learned response pattern is taught the
same way: as an entry of the list under the `"response_patterns"` key of
that same stored value - on a learned MEANING (Prompt 424), on a learned
SENTENCE PATTERN (Prompt 423 `teach(..., meaning={...})`), or on a
learned EXPRESSION's meaning (Prompt 418):

    learner.learn_item("en", "meaning", "greeting", meaning={
        "response_patterns": [
            {"id": "formal_greeting", "locale": "en-GB",
             "template": "Good morning, {{X}}."},
            {"id": "casual_greeting", "topic": "friends"},
        ]})

No new table, no new item type, no new relationship type, and no second
learning mechanism: the teaching operations (416/423/424) are untouched
and simply carry the value. This module never writes one, never creates
one and never completes one - a pattern exists for it only if it was
taught, and it is returned exactly as taught (deep-copied, payload keys
such as `template` uninterpreted).

An entry needs a non-empty text `"id"` (or `"pattern_id"` / `"name"`);
an entry without one, or one that is not a dict, is ignored - never
repaired. It may also declare CONDITIONS, each of which must be
satisfied by what the context already knows or the entry is not
eligible (a declared condition that cannot be verified - the context
has no such information, or the value is malformed - is NOT satisfied):

    language          the context's language (canonicalized, so "en"
                      and "english" agree)
    locale            the context's locale (exact, case-insensitive)
    meaning           the resolved learned meaning's name
    sentence_pattern  the matched learned sentence pattern (its id or
                      its text)
    topic             the active topic (else the conversation context's)
    reference         True: at least one RESOLVED reference; text: a
                      resolved reference with that text
    variables         names the recognized sentence structure / matched
                      pattern must have extracted values for

No condition is ever inferred, defaulted or relaxed.

Where candidates are read from (bounded, in this fixed order)
--------------------------------------------------------------
    1. the RESOLVED pattern meaning        (`language_guidance.
                                             pattern_meaning`)
    2. the matched learned sentence pattern (`matched_pattern`)
    3. RESOLVED learned expression meanings (`language_guidance.
                                             expression_meanings`)
    4. every UNDECIDED pattern-meaning candidate, only so that an
       ambiguity is preserved (never selectable)

Nothing else is consulted: no language-learning table is scanned, no
conversation history is read, and no memory or knowledge lookup is made.
Each source contributes at most `MAX_PATTERNS_PER_SOURCE` entries and at
most `MAX_CANDIDATES` entries are examined in total, taken in the order
above and, within a source, in the order taught - so the same input
always examines the same entries. `truncated` reports when a bound cut
anything off.

Statuses (same vocabulary as Prompt 420 / 433)
------------------------------------------------
    RESOLVED    exactly one candidate is the strongest eligible one.
                Strength is the number of declared conditions the
                candidate satisfies (a candidate that declares a matching
                topic is stronger than one that declares nothing); it is
                the only ranking, and it never looks at confidence,
                position, id or origin. `selected_pattern` is set.
    AMBIGUOUS   several eligible candidates are equally strong (all of
                them are kept, in taught order, none picked) - or the
                understanding itself is undecided (the plan is
                AMBIGUOUS, or the bound meaning has undecided candidates)
                and eligible candidates exist: then every eligible
                candidate is kept and NOTHING is selected, because
                picking one would settle the ambiguity the existing
                pipeline deliberately left open.
    NOT_FOUND   no learned response pattern is available, or none is
                eligible. Nothing is invented.

Result (`LearnedResponsePatternSelection.to_dict()`): `status`, `reason`,
`selected_pattern`, `candidates` (AMBIGUOUS only), `language`, `locale`
(as the context reports them), `confidence` / `source` (the selected
pattern's, when RESOLVED and already known), `truncated`. A pattern
entry (`selected_pattern`, each candidate) is `{"pattern_id", "pattern",
"origin", "matched_on", "confidence", "source"}`: the pattern as taught,
where it came from (`{"kind": meaning / sentence_pattern / expression /
undecided_meaning, "id", "name"}`), which declared conditions it
satisfied (`matched_on`, [] for a condition-free entry), and
the pattern's own confidence/source - else those of the item that
carried it.

No mutable-state leakage
-------------------------
Everything read is deep-copied first and `to_dict()` returns a fresh
deep copy on every call, so a caller can never reach the plan, the
guidance, the context or any store through a selection - or the other
way round.

Integration
-----------
`build_generation_context()` (response_generation_context.py) runs the
selector right after `build_language_guidance()`, from the SAME plan and
the guidance just built, and stores the result as
`ResponseGenerationContext.response_pattern_selection`;
`build_generation_request()` (response_generation_request.py) carries it
into `BackendGenerationRequest.response_pattern_selection` unchanged.
Both fields are additive. Nothing about `ResponseGenerationResult`,
`ConversationResponse`, the local model runtime/provider, model loading,
readiness, resource limits, timeout/cancellation or backend selection
changes, and a context with no learned response pattern simply carries a
NOT_FOUND selection.
"""

import copy
import json
import unicodedata

from .language_context import canonical_language
from .language_guidance import (
    LearnedLanguageGuidance, build_language_guidance,
    STATUS_RESOLVED as GUIDANCE_RESOLVED, STATUS_AMBIGUOUS as GUIDANCE_AMBIGUOUS,
)
from .response_planning import STATUS_AMBIGUOUS as PLAN_AMBIGUOUS, _name_key

STATUS_RESOLVED = "RESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_NOT_FOUND = "NOT_FOUND"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)

REASON_UNIQUE_BEST_MATCH = "unique_best_match"
REASON_EQUALLY_VALID = "equally_valid_response_patterns"
REASON_UNDECIDED_UNDERSTANDING = "understanding_not_decided"
REASON_NONE_AVAILABLE = "no_learned_response_pattern_available"
REASON_NONE_ELIGIBLE = "no_matching_learned_response_pattern"

# Where a candidate came from (`origin["kind"]`).
ORIGIN_MEANING = "meaning"
ORIGIN_SENTENCE_PATTERN = "sentence_pattern"
ORIGIN_EXPRESSION = "expression"
ORIGIN_UNDECIDED_MEANING = "undecided_meaning"

# The key, inside a learned item's open stored value, that carries taught
# response patterns (see the module docstring).
RESPONSE_PATTERNS_KEY = "response_patterns"

# Conditions an entry may declare, in the fixed order they are reported.
CONDITION_KEYS = (
    "language", "locale", "meaning", "sentence_pattern", "topic", "reference", "variables",
)

# Fixed bounds: the selection's cost never depends on how much was taught.
MAX_PATTERNS_PER_SOURCE = 20
MAX_CANDIDATES = 50


# ----------------------------------------------------------------------
# small helpers (pure, never raise)
# ----------------------------------------------------------------------
def _as_dict(value):
    return value if isinstance(value, dict) else None


def _as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value):
    """Comparison form of a text value: NFKC (as the pattern matcher
    normalizes messages), whitespace-collapsed, case-folded. None for
    anything that is not non-blank text."""
    if not isinstance(value, str):
        return None
    text = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    return text or None


def _locale_key(value):
    text = _text(value)
    return text.replace("_", "-") if text else None


def _entry_id(entry):
    for key in ("id", "pattern_id", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _taught_entries(stored_value):
    """The response-pattern entries taught in one item's open stored
    value: the dict entries of its `response_patterns` list that carry an
    id. Anything else is ignored, never repaired."""
    holder = _as_dict(stored_value)
    if holder is None:
        return []
    return [e for e in _as_list(holder.get(RESPONSE_PATTERNS_KEY))
            if isinstance(e, dict) and _entry_id(e) is not None]


class LearnedResponsePatternSelection:
    """Plain, JSON-shaped, read-only result of
    `LearnedResponsePatternSelector.select()` - see the module docstring.
    Same conventions as `LearnedLanguageGuidance` (language_guidance.py):
    a value holder with `to_dict()`, never anything that validates by
    raising."""

    def __init__(self, status, reason, selected_pattern, candidates, language, locale,
                 confidence, source, truncated):
        self.status = status
        self.reason = reason
        self.selected_pattern = selected_pattern
        self.candidates = candidates
        self.language = language
        self.locale = locale
        self.confidence = confidence
        self.source = source
        self.truncated = truncated

    @property
    def resolved(self):
        return self.status == STATUS_RESOLVED

    @property
    def ambiguous(self):
        return self.status == STATUS_AMBIGUOUS

    @property
    def not_found(self):
        return self.status == STATUS_NOT_FOUND

    def __repr__(self):
        selected = self.selected_pattern["pattern_id"] if self.selected_pattern else None
        return (f"LearnedResponsePatternSelection(status={self.status!r}, "
                f"selected={selected!r}, candidates={len(self.candidates)})")

    def to_dict(self):
        """A fresh deep copy every call (see the module docstring "No
        mutable-state leakage")."""
        return copy.deepcopy({
            "status": self.status,
            "reason": self.reason,
            "selected_pattern": self.selected_pattern,
            "candidates": self.candidates,
            "language": self.language,
            "locale": self.locale,
            "confidence": self.confidence,
            "source": self.source,
            "truncated": self.truncated,
        })


class LearnedResponsePatternSelector:
    """Stateless and dependency-free: it owns no storage and calls no
    other system, so one instance is safe to reuse for every call."""

    def select(self, source, language_guidance=None):
        """The `LearnedResponsePatternSelection` for `source` - a
        `ResponsePlan`, a `ResponseGenerationContext`, or the `to_dict()`
        of either - using `language_guidance` (a `LearnedLanguageGuidance`
        or its `to_dict()`), else the `language_guidance` the source
        already carries, else the guidance built from the source itself
        (`build_language_guidance`). Reads only that; never mutates it.
        A `source` of any other type raises TypeError - the same contract
        `build_generation_context()` already follows."""
        data = self._source_data(source)
        guidance = self._guidance(data, language_guidance)
        facts = self._facts(data, guidance)
        candidates, truncated = self._collect(data, guidance)
        pattern_meaning = _as_dict(guidance.get("pattern_meaning"))
        undecided = (
            data.get("status") == PLAN_AMBIGUOUS
            or bool(pattern_meaning and pattern_meaning.get("status") == GUIDANCE_AMBIGUOUS)
        )

        eligible = []
        for candidate in candidates:
            matched_on, strength = self._evaluate(candidate, facts)
            if matched_on is not None:
                eligible.append((strength, candidate, matched_on))

        language, locale = facts["language_as_reported"], data.get("locale")

        def result(status, reason, selected=None, chosen=()):
            return LearnedResponsePatternSelection(
                status=status, reason=reason,
                selected_pattern=selected,
                candidates=[self._entry(c, m) for _, c, m in chosen],
                language=language, locale=locale,
                confidence=selected["confidence"] if selected else None,
                source=selected["source"] if selected else None,
                truncated=truncated,
            )

        if not candidates:
            return result(STATUS_NOT_FOUND, REASON_NONE_AVAILABLE)
        if not eligible:
            return result(STATUS_NOT_FOUND, REASON_NONE_ELIGIBLE)
        if undecided:
            # The pipeline left the understanding open: keep every eligible
            # candidate, pick none (see the module docstring).
            return result(STATUS_AMBIGUOUS, REASON_UNDECIDED_UNDERSTANDING, chosen=eligible)
        strongest = max(strength for strength, _, _ in eligible)
        top = [item for item in eligible if item[0] == strongest]
        if len(top) > 1:
            return result(STATUS_AMBIGUOUS, REASON_EQUALLY_VALID, chosen=top)
        _, candidate, matched_on = top[0]
        return result(STATUS_RESOLVED, REASON_UNIQUE_BEST_MATCH,
                      selected=self._entry(candidate, matched_on))

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------
    @staticmethod
    def _source_data(source):
        if isinstance(source, dict):
            return copy.deepcopy(source)
        # a ResponsePlan or a ResponseGenerationContext (duck-typed here:
        # importing the context class would be circular)
        data = source.to_dict() if callable(getattr(source, "to_dict", None)) else None
        if not isinstance(data, dict):
            raise TypeError(
                "source must be a ResponsePlan, a ResponseGenerationContext or their to_dict()")
        return data

    @staticmethod
    def _guidance(data, language_guidance):
        if isinstance(language_guidance, LearnedLanguageGuidance):
            return language_guidance.to_dict()
        if isinstance(language_guidance, dict):
            return copy.deepcopy(language_guidance)
        if "language_guidance" in data:  # a context: whatever it carries, even None
            return copy.deepcopy(_as_dict(data.get("language_guidance"))) or {}
        return build_language_guidance(data).to_dict()  # a plan

    @staticmethod
    def _facts(data, guidance):
        """What the context already knows, in comparison form. A fact the
        context lacks is None/empty - and so cannot satisfy a condition."""
        reported = data.get("language", data.get("detected_language"))

        topic = _as_dict(data.get("active_topic"))
        topic = topic.get("topic") if topic else None
        if not _text(topic):  # else the conversation context's own topic
            conversation_topic = _as_dict((_as_dict(data.get("context")) or {}).get("topic"))
            topic = conversation_topic.get("topic") if conversation_topic else None

        references = []
        for item in _as_list(data.get("references")):
            item = _as_dict(item)
            if item and not item.get("ambiguous") and item.get("resolved_context") is not None:
                references.append(_text(item.get("reference_text")) or "")

        variable_names = {
            name for name, value in (_as_dict(data.get("variables")) or {}).items()
            if value is not None
        }
        structure = _as_dict(guidance.get("sentence_structure"))
        if structure and structure.get("status") == "MATCHED":
            for component in _as_list(structure.get("components")):
                component = _as_dict(component)
                if (component and component.get("kind") == "variable"
                        and component.get("value") is not None and component.get("variable_name")):
                    variable_names.add(component["variable_name"])

        pattern = _as_dict(data.get("matched_pattern"))
        meaning = _as_dict(guidance.get("pattern_meaning"))
        resolved = (_as_dict(meaning.get("meaning"))
                    if meaning and meaning.get("status") == GUIDANCE_RESOLVED else None)
        meaning_name = (resolved or {}).get("meaning_name")
        return {
            "language_as_reported": reported,
            "language": canonical_language(reported),
            "locale": _locale_key(data.get("locale")),
            "meaning": _name_key(meaning_name) if isinstance(meaning_name, str) else None,
            "pattern_id": (str(pattern["pattern_id"])
                           if pattern and pattern.get("pattern_id") is not None else None),
            "pattern_text": _text(pattern.get("pattern_text")) if pattern else None,
            "topic": _text(topic),
            "references": references,
            "variables": variable_names,
        }

    # ------------------------------------------------------------------
    # Candidates
    # ------------------------------------------------------------------
    @staticmethod
    def _collect(data, guidance):
        """`(candidates, truncated)`: the taught response-pattern entries
        of the bounded sources, in the fixed order of the module
        docstring, identical duplicates folded into their first
        occurrence."""
        sources = []  # (kind, id, name, stored value, confidence, source)
        pattern_meaning = _as_dict(guidance.get("pattern_meaning"))
        if pattern_meaning and pattern_meaning.get("status") == GUIDANCE_RESOLVED:
            meaning = _as_dict(pattern_meaning.get("meaning")) or {}
            sources.append((ORIGIN_MEANING, meaning.get("meaning_id"), meaning.get("meaning_name"),
                            meaning.get("meaning"), meaning.get("confidence"), meaning.get("source")))
        pattern = _as_dict(data.get("matched_pattern"))
        if pattern:
            sources.append((ORIGIN_SENTENCE_PATTERN, pattern.get("pattern_id"),
                            pattern.get("pattern_text"), pattern.get("meaning"),
                            pattern.get("confidence"), pattern.get("source")))
        for entry in _as_list(guidance.get("expression_meanings")):
            entry = _as_dict(entry)
            resolved = _as_dict(entry.get("resolved_meaning")) if entry else None
            if entry and entry.get("status") == GUIDANCE_RESOLVED and resolved:
                sources.append((ORIGIN_EXPRESSION, resolved.get("id"), entry.get("expression"),
                                resolved.get("meaning"), resolved.get("confidence"),
                                resolved.get("source")))
        if pattern_meaning and pattern_meaning.get("status") == GUIDANCE_AMBIGUOUS:
            for meaning in _as_list(pattern_meaning.get("candidates")):
                meaning = _as_dict(meaning) or {}
                sources.append((ORIGIN_UNDECIDED_MEANING, meaning.get("meaning_id"),
                                meaning.get("meaning_name"), meaning.get("meaning"),
                                meaning.get("confidence"), meaning.get("source")))

        candidates, seen, truncated = [], set(), False
        for kind, item_id, name, stored, confidence, source in sources:
            entries = _taught_entries(stored)
            if len(entries) > MAX_PATTERNS_PER_SOURCE:
                entries, truncated = entries[:MAX_PATTERNS_PER_SOURCE], True
            for entry in entries:
                if len(candidates) >= MAX_CANDIDATES:
                    truncated = True
                    break
                fingerprint = json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                candidates.append({
                    "entry": copy.deepcopy(entry),
                    "origin": {"kind": kind, "id": copy.deepcopy(item_id),
                               "name": copy.deepcopy(name)},
                    "confidence": confidence, "source": source,
                })
        return candidates, truncated

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------
    @staticmethod
    def _evaluate(candidate, facts):
        """`(matched_on, strength)` when every condition the entry
        declares is satisfied (`matched_on`: those conditions, in
        `CONDITION_KEYS` order; `strength`: how many), or `(None, 0)`
        when any is not."""
        entry = candidate["entry"]
        checks = {
            "language": lambda v: (canonical_language(v) is not None
                                   and canonical_language(v) == facts["language"]),
            "locale": lambda v: _locale_key(v) is not None and _locale_key(v) == facts["locale"],
            "meaning": lambda v: (isinstance(v, str) and _text(v) is not None
                                  and _name_key(v) == facts["meaning"]),
            "sentence_pattern": lambda v: (
                isinstance(v, (str, int)) and not isinstance(v, bool)
                and ((facts["pattern_id"] is not None and str(v).strip() == facts["pattern_id"])
                     or (_text(v) is not None and _text(v) == facts["pattern_text"]))),
            "topic": lambda v: _text(v) is not None and _text(v) == facts["topic"],
            "reference": lambda v: (
                bool(facts["references"]) if v is True
                else (_text(v) is not None and _text(v) in facts["references"])),
            "variables": lambda v: (
                isinstance(v, (list, tuple)) and bool(v)
                and all(isinstance(n, str) and n in facts["variables"] for n in v)),
        }
        matched_on = []
        for key in CONDITION_KEYS:
            if key not in entry or entry[key] is None:
                continue
            if not checks[key](entry[key]):
                return None, 0
            matched_on.append(key)
        return matched_on, len(matched_on)

    @staticmethod
    def _entry(candidate, matched_on):
        entry = candidate["entry"]
        confidence = entry.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            confidence = candidate["confidence"]
        source = entry.get("source")
        if not isinstance(source, str) or not source.strip():
            source = candidate["source"]
        return {
            "pattern_id": _entry_id(entry),
            "pattern": copy.deepcopy(entry),
            "origin": copy.deepcopy(candidate["origin"]),
            "matched_on": list(matched_on),
            "confidence": confidence,
            "source": source,
        }


def select_learned_response_pattern(source, language_guidance=None):
    """`LearnedResponsePatternSelector().select(...)` as a plain function -
    the convenience `build_generation_context()` uses."""
    return LearnedResponsePatternSelector().select(source, language_guidance)


def response_pattern_selection_from_understanding(understanding):
    """The selection for the `response_plan` already attached to
    `understanding`, using the guidance `language_guidance_from_
    understanding` builds from it (Prompt 433, including
    `understanding.learned_sentence_structure`). None when there is no
    plan to read yet - same as `generation_context_from_understanding`
    (response_generation_context.py). Never plans, matches or resolves
    anything itself."""
    from .language_guidance import language_guidance_from_understanding
    plan = getattr(understanding, "response_plan", None)
    if plan is None:
        return None
    return select_learned_response_pattern(plan, language_guidance_from_understanding(understanding))
