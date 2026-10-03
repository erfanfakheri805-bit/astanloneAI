"""
Conversation Context - Lightweight Conversation State (Prompt 405)
====================================================================
A small, bounded, in-RAM record of what is worth remembering about a
long conversation WITHOUT keeping (or sending) the conversation itself:

    USER INPUT -> Relevance Selection (relevance.py)
               -> Reference Resolution (message_reference_resolution.py)
               -> Active Topic + thread (active_topic.py)
               -> CONVERSATION STATE (this module)        <- Prompt 405
               -> LanguageUnderstandingResult.conversation_state
               -> select_relevant_state()  (this module)
               -> build_inference_request  (local_model_mapping.py,
                  bounded by Prompt 404's size control)

It is NOT a memory system, NOT a second history and NOT a second
selection pipeline. It adds only what no existing structure keeps:

  * the topics that were active EARLIER (ActiveTopicTracker holds only
    the current one - an unrelated message replaces it there, which is
    right for response construction but would lose "the robot game" for
    good after one off-topic question). Each is a topic phrase and a few
    key words, never messages;
  * explicit user preferences ("I prefer ...", "keep it short") - the
    one thing a topic tracker cannot express;
  * unresolved references (a "it" that pointed at nothing yet).

Everything else is READ from what the pipeline already produced for the
same message - the ActiveTopicResult, the ConversationThreadState and the
ResolvedReference are inputs to update(), never recomputed here, and the
reference target is kept as a few words, not as the earlier message.
Response language is deliberately NOT tracked: LanguageContext already
records the requested language (Prompt 401).

BOUNDS (every collection has a fixed cap; nothing grows with the length
of the conversation)
    background topics   DEFAULT_MAX_BACKGROUND_TOPICS, least recently
                        active evicted first
    preferences         DEFAULT_MAX_PREFERENCES, oldest evicted first
    unresolved refs     DEFAULT_MAX_UNRESOLVED, oldest evicted first
    key words per topic MAX_KEY_TERMS; per reference MAX_REFERENCE_TERMS
    preference text     MAX_PREFERENCE_CHARS
`max_age` (Core passes the ConversationContext's own `max_size`, the
existing limit) is how many messages a background topic or an unresolved
reference may go untouched before it is dropped as obsolete.

UPDATE RULES (update(), once per handled conversational message)
    1. Nothing is overwritten because a message is unrelated: a topic
       that stops being active is demoted to a background topic, not
       deleted; a message without a topic changes no topic.
    2. Returning to a background topic promotes it again, keeping its
       words.
    3. A preference of the same kind replaces the older one ("keep it
       short" then "explain in detail"); "I no longer prefer X" removes
       it.
    4. An unresolved reference is dropped once the same reference later
       resolves, or when it ages out.
    5. Nothing is invented: only explicit statements match the
       (English-only, like the rest of term extraction) preference
       patterns, and only existing pipeline results feed the topics.

SELECTION (select_relevant_state / format_state_text)
    The whole state is never sent just because it exists. For one
    message: the active topic and the preferences always apply; a
    background topic only when the message shares a word with it; the
    unresolved references only when the message itself contains a
    reference word. What remains is rendered as a few short lines and
    fitted into whatever room Prompt 404's size control leaves - whole
    lines are dropped (least important first), text is never cut
    mid-line, and no room means no state.
"""

import re

from understanding.normalization import normalize
from .active_topic import content_terms
from .reference_resolution import SINGULAR_PRONOUNS, PLURAL_PRONOUNS

DEFAULT_MAX_BACKGROUND_TOPICS = 3
DEFAULT_MAX_PREFERENCES = 3
DEFAULT_MAX_UNRESOLVED = 2
DEFAULT_MAX_AGE = 10
MAX_KEY_TERMS = 8
MAX_REFERENCE_TERMS = 5
MAX_PREFERENCE_CHARS = 80
MAX_REFERENCE_CHARS = 40

# Default ceiling on the rendered state text (characters). Prompt 404's
# budget can only make it smaller.
DEFAULT_STATE_MAX_CHARS = 600

_WORD_RE = re.compile(r"[a-z0-9_']+")
_REFERENCE_WORDS = SINGULAR_PRONOUNS | PLURAL_PRONOUNS | {"he", "she"}

# ---- explicit preference patterns (fixed, English-only, deterministic) ----
_PREFER_RE = re.compile(r"\bi\s+(?:would\s+|'d\s+|really\s+|do\s+)?prefer\s+([^.!?;\n]{2,})")
_NO_LONGER_PREFER_RE = re.compile(r"\bi\s+no\s+longer\s+prefer\s+([^.!?;\n]{2,})")
_SHORT_RE = re.compile(
    r"\b(?:keep|make)\s+(?:it|them|answers|replies|responses)?\s*(?:short|brief|concise)\b"
    r"|\bbe\s+(?:brief|concise|short)\b"
    r"|\bshort(?:er)?\s+(?:answers|replies|responses)\b"
)
_DETAILED_RE = re.compile(
    r"\bin\s+detail\b"
    r"|\bdetailed\s+(?:answers|replies|responses|explanations)\b"
    r"|\bbe\s+(?:detailed|thorough)\b"
)
_DISPREFERRED_RE = re.compile(r"\b(?:over|rather\s+than|instead\s+of|more\s+than)\b")
_KEY_LENGTH = "response_length"
_TEXT_SHORT = "prefers short answers"
_TEXT_DETAILED = "prefers detailed answers"


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _dedupe(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _key_terms(topic, *term_lists):
    """The topic's own words first, then the most recently introduced
    extra words, capped at MAX_KEY_TERMS."""
    topic_words = (topic or "").split()
    extras = []
    for terms in term_lists:
        for term in terms or ():
            if term not in topic_words:
                extras.append(term)
    extras = _dedupe(extras)
    room = max(0, MAX_KEY_TERMS - len(topic_words))
    return topic_words + (extras[-room:] if room else [])


class _TopicRecord:
    def __init__(self, topic, terms, last_turn):
        self.topic = topic
        self.terms = list(terms)
        self.reference_terms = []
        self.last_turn = last_turn

    def to_dict(self):
        return {"topic": self.topic, "terms": list(self.terms),
                "reference_terms": list(self.reference_terms)}


class ConversationState:
    """One instance per Core, alongside ConversationContext and
    ActiveTopicTracker (same isolation pattern: in-memory, single-
    threaded, cleared by reset()). Holds words and short phrases - never
    whole messages."""

    def __init__(self, max_age=DEFAULT_MAX_AGE,
                 max_background_topics=DEFAULT_MAX_BACKGROUND_TOPICS,
                 max_preferences=DEFAULT_MAX_PREFERENCES,
                 max_unresolved=DEFAULT_MAX_UNRESOLVED):
        for name, value in (("max_age", max_age),
                            ("max_background_topics", max_background_topics),
                            ("max_preferences", max_preferences),
                            ("max_unresolved", max_unresolved)):
            if not _is_positive_int(value):
                raise ValueError(f"{name} must be a positive int")
        self.max_age = max_age
        self.max_background_topics = max_background_topics
        self.max_preferences = max_preferences
        self.max_unresolved = max_unresolved
        self.reset()

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def update(self, text, active_topic=None, thread=None, resolved_reference=None):
        """Fold the results the pipeline already produced for `text`
        into the state. `active_topic` is the ActiveTopicResult, `thread`
        the ConversationThreadState and `resolved_reference` the
        ResolvedReference of the same message (all optional). Never
        raises, never mutates an argument, never stores `text`."""
        self._turn += 1
        # A message that only states a preference ("keep it short") is not
        # a new subject and its "it" points at nothing: it changes
        # preferences only, so topics and references are left untouched.
        if self._update_preferences(text):
            # The tracker may have turned the statement's own words into its
            # topic; do not adopt that topic (even on later messages that
            # merely keep it).
            self._ignored_topic = (
                getattr(active_topic, "topic", None) if getattr(active_topic, "changed", False) else None)
        else:
            self._update_topics(active_topic, thread)
            self._update_references(resolved_reference)
        self._expire()

    def _update_topics(self, active_topic, thread):
        topic = getattr(active_topic, "topic", None)
        if not topic or topic == self._ignored_topic:
            return  # nothing known this turn: no topic is changed or dropped
        thread_terms = list(getattr(thread, "terms", None) or [])
        active = self._active
        if active is not None and active.topic == topic:
            active.terms = _key_terms(topic, active.terms, thread_terms)
            active.last_turn = self._turn
            return
        if active is not None:
            self._demote(active)
        promoted = next((r for r in self._background if r.topic == topic), None)
        if promoted is not None:
            self._background.remove(promoted)
            promoted.terms = _key_terms(topic, promoted.terms, thread_terms)
            promoted.last_turn = self._turn
            self._active = promoted
        else:
            self._active = _TopicRecord(topic, _key_terms(topic, thread_terms), self._turn)

    def _demote(self, record):
        self._background = [r for r in self._background if r.topic != record.topic]
        self._background.append(record)
        while len(self._background) > self.max_background_topics:
            oldest = min(self._background, key=lambda r: r.last_turn)
            self._background.remove(oldest)

    def _update_references(self, resolved_reference):
        if resolved_reference is None or not getattr(resolved_reference, "has_reference", False):
            return
        reference = (getattr(resolved_reference, "reference_text", None) or "")[:MAX_REFERENCE_CHARS]
        resolved_text = getattr(resolved_reference, "resolved_context", None)
        if resolved_text and not getattr(resolved_reference, "ambiguous", False):
            # Resolved: an earlier open reference of the same kind is closed,
            # and the target is kept as a few words, not as the message.
            self._unresolved = [u for u in self._unresolved if u["reference"] != reference]
            if self._active is not None:
                self._active.reference_terms = _dedupe(
                    self._active.reference_terms + content_terms(resolved_text)
                )[-MAX_REFERENCE_TERMS:]
            return
        if not reference:
            return
        self._unresolved = [u for u in self._unresolved if u["reference"] != reference]
        self._unresolved.append({
            "reference": reference,
            "topic": self._active.topic if self._active is not None else None,
            "turn": self._turn,
        })
        del self._unresolved[:-self.max_unresolved]

    def _update_preferences(self, text):
        """Apply an explicit preference statement in `text`, if any.
        Returns True when `text` was one (matched or retracted)."""
        normalized = normalize(text or "").normalized_text.lower()
        if not normalized or normalized.rstrip().endswith("?"):
            return False  # a question is not a stated preference
        match = _NO_LONGER_PREFER_RE.search(normalized)
        if match:
            words = set(_WORD_RE.findall(match.group(1)))
            self._preferences = [p for p in self._preferences if p["key"] not in words]
            return True
        match = _PREFER_RE.search(normalized)
        if match:
            # Only the preferred part: "short answers over long ones" -> "short answers".
            phrase = _DISPREFERRED_RE.split(match.group(1), maxsplit=1)[0].strip()
            phrase = phrase[:MAX_PREFERENCE_CHARS - len("prefers ")].strip()
            if self._set_length_preference(phrase):
                return True
            terms = content_terms(phrase)
            if terms:
                self._set_preference(terms[0], "prefers " + phrase)
                return True
            return False
        return self._set_length_preference(normalized)

    def _set_length_preference(self, text):
        if _SHORT_RE.search(text):
            self._set_preference(_KEY_LENGTH, _TEXT_SHORT)
            return True
        if _DETAILED_RE.search(text):
            self._set_preference(_KEY_LENGTH, _TEXT_DETAILED)
            return True
        return False

    def _set_preference(self, key, text):
        self._preferences = [p for p in self._preferences if p["key"] != key]
        self._preferences.append({"key": key, "text": text[:MAX_PREFERENCE_CHARS]})
        del self._preferences[:-self.max_preferences]

    def _expire(self):
        limit = self._turn - self.max_age
        self._background = [r for r in self._background if r.last_turn > limit]
        self._unresolved = [u for u in self._unresolved if u["turn"] > limit]

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def to_dict(self):
        """The whole (bounded) state as plain JSON-shaped data - safe to
        hand across a module boundary; a caller cannot alter the state
        through it."""
        return {
            "turn": self._turn,
            "topic": self._active.to_dict() if self._active is not None else None,
            "background_topics": [r.to_dict() for r in self._background],
            "preferences": [dict(p) for p in self._preferences],
            "unresolved_references": [
                {"reference": u["reference"], "topic": u["topic"]} for u in self._unresolved
            ],
        }

    def reset(self):
        self._turn = 0
        self._active = None
        self._background = []
        self._preferences = []
        self._unresolved = []
        self._ignored_topic = None


# ----------------------------------------------------------------------
# Selection and rendering (used by local_model_mapping.py)
# ----------------------------------------------------------------------
def _terms_of(record):
    return set((record.get("topic") or "").split()) | set(record.get("terms") or ())


def select_relevant_state(state, message):
    """The part of `state` (a ConversationState.to_dict() dict) that bears
    on `message`, in the same shape, or None when nothing does. Pure and
    never raises. See the module docstring for the rules."""
    if not isinstance(state, dict):
        return None
    message_terms = set(content_terms(message)) if isinstance(message, str) else set()
    words = set(_WORD_RE.findall(normalize(message or "").normalized_text.lower())) \
        if isinstance(message, str) else set()

    topic = state.get("topic") if isinstance(state.get("topic"), dict) else None
    preferences = [p for p in (state.get("preferences") or []) if isinstance(p, dict)]
    background = [
        r for r in (state.get("background_topics") or [])
        if isinstance(r, dict) and message_terms & _terms_of(r)
    ]
    unresolved = (
        [u for u in (state.get("unresolved_references") or []) if isinstance(u, dict)]
        if words & _REFERENCE_WORDS else []
    )
    if not (topic or preferences or background or unresolved):
        return None
    return {
        "topic": topic,
        "background_topics": background,
        "preferences": preferences,
        "unresolved_references": unresolved,
    }


def format_state_text(selected, max_chars=DEFAULT_STATE_MAX_CHARS):
    """Render a select_relevant_state() result as short lines, fitted to
    `max_chars`. Lines are kept in priority order (topic, preferences,
    unresolved references, related words, earlier topics) and whole
    lines are dropped from the end when they do not fit - text is never
    cut mid-line. Returns "" when there is nothing to say or no room."""
    if not isinstance(selected, dict):
        return ""
    if not isinstance(max_chars, (int, float)) or isinstance(max_chars, bool) or max_chars <= 0:
        return ""
    topic = selected.get("topic") if isinstance(selected.get("topic"), dict) else None
    lines = []
    if topic and topic.get("topic"):
        lines.append(f"topic: {topic['topic']}")
    for p in selected.get("preferences") or []:
        if p.get("text"):
            lines.append(f"preference: {p['text']}")
    for u in selected.get("unresolved_references") or []:
        if u.get("reference"):
            suffix = f" (topic: {u['topic']})" if u.get("topic") else ""
            lines.append(f"unresolved reference: {u['reference']}{suffix}")
    if topic and topic.get("topic"):
        related = [t for t in (topic.get("terms") or []) + (topic.get("reference_terms") or [])
                   if t not in topic["topic"].split()]
        related = _dedupe(related)
        if related:
            lines.append("related: " + ", ".join(related))
    for r in selected.get("background_topics") or []:
        if r.get("topic"):
            lines.append(f"earlier topic: {r['topic']}")
    header = "conversation state:"
    kept, total = [], len(header)
    for line in lines:
        if total + 1 + len(line) > max_chars:
            break
        kept.append(line)
        total += 1 + len(line)
    return header + "\n" + "\n".join(kept) if kept else ""
