"""
Conversation Context - Active Conversation Topic (Prompt 393)
===============================================================
A small, deterministic step that sits after Reference Resolution
(context/message_reference_resolution.py, Prompt 392) and before/
alongside Response Construction (core/core.py's
`_construct_fallback_reply`, Prompt 391): it keeps one simple,
structured answer to "what is the main thing being talked about right
now?" so later pipeline stages can read it without re-deriving it.

    USER INPUT -> Relevance Selection (relevance.py)
               -> Reference Resolution (message_reference_resolution.py)
               -> ACTIVE TOPIC (this module)
               -> Response Construction

This is NOT a memory system, NOT an NLU engine and NOT semantic topic
modeling. It holds exactly one short string (plus the result of the
last update), lives only in process RAM next to ConversationContext,
and is cleared by Core.reset_context(). It reuses the already-selected
RelevantContextResult and the already-produced ResolvedReference - it
never selects context or resolves references itself, and it never
touches or replaces the original user message.

HOW A TOPIC IS DERIVED
-----------------------
The topic phrase is made of the message's meaningful words
(understanding/term_extraction.py, the same extractor relevance.py
uses) minus a small fixed list of conversational filler ("want",
"make", "three", ...), in the order they were written, at most
`_MAX_TOPIC_TERMS` of them. One tiny rule reorders a very common
shape: "<head> about <subject>" becomes "<subject> <head>" - so
"I am building a game about a robot." gives "robot game". Nothing
else is inferred: a message with no meaningful words yields no topic.

DECISION ORDER (first match wins; fixed, no scoring model)
------------------------------------------------------------
    1. Resolved reference (ambiguous/unresolved ones are ignored):
       if the turn it points to shares a word with the current topic,
       the topic is kept; otherwise (or with no topic yet) the topic
       is derived from that resolved turn.
    2. Explicit shift marker ("by the way", "new topic", ...): the
       topic becomes whatever the rest of the message is about. A
       marker with nothing after it changes nothing.
    3. No meaningful words ("Tell me more.", "Okay.", a non-Latin
       message): the current topic is kept; with none, no topic is
       invented.
    4. No current topic yet: derived from the message.
    5. Shares a word with the current topic or with the current
       thread's recent turns (Prompt 395), or with a selected relevant
       turn that is itself about them: kept. An "ambiguous" reference
       (step 1b) leaves the topic as it was and claims no relationship.
       Also kept: an elliptical "what about X?" / "how about X?", and
       (Prompt 394) a request for "ideas"/"features"/...
       that names no subject of its own.
    6. Otherwise: the message is about something unrelated to the
       current topic - the topic changes to the new subject.

THREAD (Prompt 395)
--------------------
Around the topic the tracker keeps one small conversation-thread
record (ConversationThreadState): a thread id, how many messages belong
to it, the meaningful words of its recent turns, the last resolved
reference, and how the latest message relates to it - new_topic,
follow_up, isolated or ambiguous. A message is judged against the
whole thread, so in "I am building a game about a robot." / "What
about the boss?" / "How should the boss attack?" the third message
continues the thread through the word "boss" the second one added. The
thread's word memory is bounded by the same limit as the
ConversationContext (see ActiveTopicTracker).

Confidence values are fixed constants per rule below, never learned or
randomized.
"""

import re
from collections import deque

from understanding.normalization import normalize
from understanding.term_extraction import extract_candidate_terms
from .reference_resolution import SINGULAR_PRONOUNS, PLURAL_PRONOUNS

_MAX_TOPIC_TERMS = 3
_REFERENCE_WORDS = SINGULAR_PRONOUNS | PLURAL_PRONOUNS | {"he", "she"}

# Conversational filler that is never itself the subject of a
# conversation. Deliberately small - same "small and reliable rather
# than exhaustive" convention as the stopword list it extends.
_FILLER_WORDS = {
    "am", "i'm", "i've", "i'll", "i'd", "ive", "ill", "id", "dont", "don't", "cant", "can't",
    "want", "wants", "wanna", "need", "needs", "like", "make", "making", "makes",
    "build", "building", "built", "create", "creating", "give", "get", "getting",
    "have", "has", "had", "use", "using", "try", "trying", "help", "show", "let", "lets",
    "let's", "going", "gonna", "think", "thing", "things", "idea", "ideas", "more",
    "another", "also", "just", "yes", "no", "yeah", "ok", "okay", "thanks", "thank",
    "hi", "hello", "hey", "so", "then", "but", "not", "by", "way", "at", "as", "into",
    "if", "than", "there", "here", "from", "will", "may", "might", "much", "many",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "first", "second", "next", "new", "other", "add", "say", "said", "mentioned",
}

_SHIFT_MARKERS = (
    "by the way",
    "new topic",
    "different topic",
    "another topic",
    "change the subject",
    "changing the subject",
    "switching topics",
    "on another note",
    "unrelated question",
    "unrelated",
    "anyway",
)

# "<head> about <subject>": "game about a robot" -> "robot game".
_ABOUT_RE = re.compile(r"\b([a-z][a-z0-9_']*)\s+about\s+(?:a|an|the|my|our)?\s*([a-z][a-z0-9_']*)\b")

# Requests for "ideas", "features", ... are inherently *about
# something else*: their subject is deferred to context. Such a message
# is a dependent follow-up of the current topic unless it names its own
# subject after a preposition ("ideas for Python").
_DEPENDENT_REQUEST_WORDS = {
    "idea", "ideas", "feature", "features", "option", "options", "suggestion",
    "suggestions", "tip", "tips", "example", "examples", "improvement",
    "improvements", "step", "steps", "name", "names", "way", "ways",
    "recommendation", "recommendations",
}
_SUBJECT_INTRODUCER_RE = re.compile(
    r"\b(?:for|about|on|in|with|using|regarding)\s+(?:a|an|the|my|our)?\s*([a-z][a-z0-9_']*)"
)

SOURCE_CURRENT_INPUT = "current_input"
SOURCE_RESOLVED_REFERENCE = "resolved_reference"
SOURCE_SHIFT_MARKER = "topic_shift_marker"
SOURCE_PREVIOUS_TOPIC = "previous_topic"

_CONF_NEW_FROM_INPUT = 0.7
_CONF_SHIFT_MARKER = 0.8
_CONF_KEPT_SHARED_TERMS = 0.8
_CONF_KEPT_FROM_CONTEXT = 0.7
_CONF_KEPT_NO_SIGNAL = 0.6
_CONF_KEPT_MARKER_ONLY = 0.4


class ActiveTopicResult:
    """Structured result of one active-topic update - same plain,
    JSON-shaped convention as ResolvedReference / RelevantContextResult.

    `topic` is None when nothing is known (never a placeholder string).
    `topic_source` is one of the SOURCE_* constants (None with no
    topic). `changed` is True exactly when `topic` differs from
    `previous_topic`. `reason` is a short debugging string."""

    def __init__(self, topic, topic_source, confidence, changed, previous_topic, reason):
        self.topic = topic
        self.topic_source = topic_source
        self.confidence = confidence
        self.changed = changed
        self.previous_topic = previous_topic
        self.reason = reason

    def __repr__(self):
        return (
            f"ActiveTopicResult(topic={self.topic!r}, topic_source={self.topic_source!r}, "
            f"confidence={self.confidence:.2f}, changed={self.changed}, "
            f"previous_topic={self.previous_topic!r})"
        )

    def to_dict(self):
        return {
            "topic": self.topic,
            "topic_source": self.topic_source,
            "confidence": round(self.confidence, 4),
            "changed": self.changed,
            "previous_topic": self.previous_topic,
            "reason": self.reason,
        }


def _normalized_lower(text):
    return normalize(text or "").normalized_text.lower()


def _strip_shift_marker(normalized):
    """Return (found, remainder) - `remainder` is `normalized` with
    the first shift marker removed."""
    for marker in _SHIFT_MARKERS:
        match = re.search(r"\b" + re.escape(marker) + r"\b", normalized)
        if match:
            return True, (normalized[:match.start()] + " " + normalized[match.end():])
    return False, normalized


def _content_terms(normalized):
    return [
        t for t in extract_candidate_terms(normalized)
        if t not in _FILLER_WORDS and t not in _REFERENCE_WORDS and not t.isdigit()
    ]


def _topic_phrase(normalized):
    """The topic phrase for already-normalized lowercase text, or None
    when it has no meaningful words."""
    terms = _content_terms(normalized)
    if not terms:
        return None
    match = _ABOUT_RE.search(normalized)
    if match and match.group(1) in terms and match.group(2) in terms and match.group(1) != match.group(2):
        head, subject = match.group(1), match.group(2)
        rest = [t for t in terms if t not in (head, subject)]
        terms = ([subject, head] + rest)
    return " ".join(terms[:_MAX_TOPIC_TERMS])


def _is_dependent_request(normalized, terms):
    """True for a request for ideas/features/... that does not name a
    subject of its own (no "for/about/... <new term>")."""
    words = set(re.findall(r"[a-z0-9_']+", normalized))
    if not (words & _DEPENDENT_REQUEST_WORDS):
        return False
    for match in _SUBJECT_INTRODUCER_RE.finditer(normalized):
        if match.group(1) in terms:
            return False
    return True


_ELLIPTICAL_RE = re.compile(r"^(?:and\s+|but\s+|so\s+)?(?:what|how)\s+about\b|^(?:and\s+)?what\s+if\b")

# Continuation statuses (Prompt 395). One of these describes how the
# latest message relates to the conversation thread.
STATUS_NEW_TOPIC = "new_topic"
STATUS_FOLLOW_UP = "follow_up"
STATUS_ISOLATED = "isolated"
STATUS_AMBIGUOUS = "ambiguous"

DEFAULT_THREAD_WINDOW = 10

_FOLLOW_UP_REASONS = {
    "shares_terms_with_topic",
    "shares_terms_with_thread",
    "relevant_context_on_topic",
    "reference_matches_current_topic",
    "dependent_request_on_topic",
    "elliptical_follow_up",
}
_NEW_TOPIC_REASONS = {"first_topic", "unrelated_to_current_topic", "explicit_topic_shift"}


def content_terms(text):
    """The meaningful words of `text` (shift marker, filler, pronouns
    and numbers removed), in written order - what a thread remembers
    about a message instead of the message itself."""
    _, remainder = _strip_shift_marker(_normalized_lower(text))
    return _content_terms(remainder)


def _is_elliptical_follow_up(normalized):
    """"What about the boss?" / "How about ...?" / "What if ...?" - a
    message whose meaning is only defined by the discussion so far."""
    return bool(_ELLIPTICAL_RE.search(normalized.strip()))


def _overlaps(terms, topic, extra_terms=()):
    known = set(topic.split()) if topic else set()
    known |= set(extra_terms or ())
    return bool(known) and bool(set(terms) & known)


def _result(topic, source, confidence, previous_topic, reason):
    return ActiveTopicResult(topic, source, confidence, topic != previous_topic, previous_topic, reason)


def determine_active_topic(text, previous_topic=None, relevant_context=None, resolved_reference=None,
                           thread_terms=None):
    """Pure function: decide the active topic for `text` given the
    `previous_topic` (a string or None), the RelevantContextResult
    already selected for `text` and the ResolvedReference already
    produced for it (both optional). `thread_terms` (Prompt 395) are
    the meaningful words of the recent turns of the current
    conversation thread, so a message is judged against the whole
    thread rather than only the topic phrase. Never raises, never
    mutates any argument, never fabricates a topic without meaningful
    words to build it from."""
    normalized = _normalized_lower(text)
    thread_terms = set(thread_terms or ())

    # 1. Resolved reference.
    if (resolved_reference is not None and resolved_reference.has_reference
            and not resolved_reference.ambiguous and resolved_reference.resolved_context):
        ref_normalized = _normalized_lower(resolved_reference.resolved_context)
        if _overlaps(_content_terms(ref_normalized), previous_topic, thread_terms):
            return _result(previous_topic, SOURCE_RESOLVED_REFERENCE,
                           max(resolved_reference.confidence, _CONF_KEPT_SHARED_TERMS),
                           previous_topic, "reference_matches_current_topic")
        ref_topic = _topic_phrase(ref_normalized)
        if ref_topic:
            return _result(ref_topic, SOURCE_RESOLVED_REFERENCE, resolved_reference.confidence,
                           previous_topic, "topic_from_resolved_reference")

    # 1b. An ambiguous reference: we do not know what the message points
    # at, so no relationship is invented and the topic is left as it
    # was (unless the message explicitly changes subject, below).
    ambiguous_reference = (resolved_reference is not None and resolved_reference.has_reference
                           and resolved_reference.ambiguous)

    # 2. Explicit shift marker.
    has_marker, remainder = _strip_shift_marker(normalized)
    if has_marker:
        new_topic = _topic_phrase(remainder)
        if new_topic:
            return _result(new_topic, SOURCE_SHIFT_MARKER, _CONF_SHIFT_MARKER,
                           previous_topic, "explicit_topic_shift")
        if previous_topic:
            return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_MARKER_ONLY,
                           previous_topic, "shift_marker_without_new_topic")
        return _result(None, None, 0.0, previous_topic, "insufficient_information")

    if ambiguous_reference and previous_topic:
        return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_MARKER_ONLY,
                       previous_topic, "ambiguous_reference")

    terms = _content_terms(normalized)

    # 3. Nothing to build a topic from.
    if not terms:
        if previous_topic:
            return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_NO_SIGNAL,
                           previous_topic, "no_new_terms")
        return _result(None, None, 0.0, previous_topic, "insufficient_information")

    new_topic = _topic_phrase(normalized)

    # 4. First topic.
    if not previous_topic:
        return _result(new_topic, SOURCE_CURRENT_INPUT, _CONF_NEW_FROM_INPUT,
                       previous_topic, "first_topic")

    # 5. Continuation of the topic, or of the wider thread.
    if _overlaps(terms, previous_topic):
        return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_SHARED_TERMS,
                       previous_topic, "shares_terms_with_topic")
    if _overlaps(terms, None, thread_terms):
        return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_FROM_CONTEXT,
                       previous_topic, "shares_terms_with_thread")
    selected = list(relevant_context.selected) if relevant_context is not None else []
    for item in selected:
        user_text = (item.get("turn") or {}).get("user")
        if _overlaps(_content_terms(_normalized_lower(user_text)), previous_topic, thread_terms):
            return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_FROM_CONTEXT,
                           previous_topic, "relevant_context_on_topic")

    # 5b. A request whose meaning is deferred to the discussion so far.
    if _is_elliptical_follow_up(normalized):
        return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_FROM_CONTEXT,
                       previous_topic, "elliptical_follow_up")
    if _is_dependent_request(normalized, terms):
        return _result(previous_topic, SOURCE_PREVIOUS_TOPIC, _CONF_KEPT_FROM_CONTEXT,
                       previous_topic, "dependent_request_on_topic")

    # 6. Clear change of subject.
    return _result(new_topic, SOURCE_CURRENT_INPUT, _CONF_NEW_FROM_INPUT,
                   previous_topic, "unrelated_to_current_topic")


def _continuation_status(result):
    """Map one ActiveTopicResult to a STATUS_* value."""
    reason = result.reason
    if reason in _FOLLOW_UP_REASONS:
        return STATUS_FOLLOW_UP
    if reason == "topic_from_resolved_reference":
        # No topic before: the message points back at an earlier turn,
        # which makes it a follow-up. A different topic before: a
        # change of subject.
        return STATUS_FOLLOW_UP if result.previous_topic is None else STATUS_NEW_TOPIC
    if reason in _NEW_TOPIC_REASONS:
        return STATUS_NEW_TOPIC
    if reason == "ambiguous_reference":
        return STATUS_AMBIGUOUS
    return STATUS_ISOLATED


class ConversationThreadState:
    """Snapshot of the current conversation thread after one update -
    the "thread" part of Core.last_response_context (Prompt 395).

      thread_id                 1, 2, ... - a new topic starts a new
                                thread; 0 before any thread exists
      topic                     the thread's active topic (or None)
      continuation              how the latest message relates to the
                                thread: new_topic / follow_up /
                                isolated / ambiguous
      turn_count                messages that belong to this thread
      last_resolved_reference   verbatim text of the earlier turn the
                                latest resolved reference pointed to
      terms                     meaningful words of the thread's recent
                                turns (bounded, see ActiveTopicTracker)

    Holds words, never whole messages."""

    def __init__(self, thread_id, topic, continuation, turn_count, last_resolved_reference, terms):
        self.thread_id = thread_id
        self.topic = topic
        self.continuation = continuation
        self.turn_count = turn_count
        self.last_resolved_reference = last_resolved_reference
        self.terms = list(terms)

    def __repr__(self):
        return (
            f"ConversationThreadState(thread_id={self.thread_id}, topic={self.topic!r}, "
            f"continuation={self.continuation!r}, turn_count={self.turn_count})"
        )

    def to_dict(self):
        return {
            "thread_id": self.thread_id,
            "topic": self.topic,
            "continuation": self.continuation,
            "turn_count": self.turn_count,
            "last_resolved_reference": self.last_resolved_reference,
            "terms": list(self.terms),
        }


class ActiveTopicTracker:
    """Holds the one active topic - and, since Prompt 395, the one
    current conversation thread around it - for a conversation.
    In-memory only, single-threaded, one instance per Core - same
    isolation pattern as ConversationContext. It stores a string, the
    last result and a small thread record; nothing about the user's
    message is kept or altered here.

    `window` bounds the thread memory: the thread remembers the
    meaningful words of at most its last `window` messages (one word
    list per message, oldest dropped first). Core passes the
    ConversationContext's own `max_size`, so the existing context limit
    stays in control of how much can be remembered - the thread never
    outlives what the bounded context could itself still hold."""

    def __init__(self, window=DEFAULT_THREAD_WINDOW):
        if window < 1:
            raise ValueError("window must be at least 1")
        self.window = window
        self.reset()

    def update(self, text, relevant_context=None, resolved_reference=None):
        """Compute the active topic for `text`, remember it, update the
        thread, and return the ActiveTopicResult. Does not record
        `text` anywhere."""
        result = determine_active_topic(
            text, self._topic, relevant_context, resolved_reference,
            thread_terms=self._thread_terms(),
        )
        status = _continuation_status(result)
        turn_terms = content_terms(text)
        resolved_text = None
        if (resolved_reference is not None and resolved_reference.has_reference
                and not resolved_reference.ambiguous):
            resolved_text = resolved_reference.resolved_context

        if status == STATUS_NEW_TOPIC:
            self._thread_id += 1
            self._turn_terms = self._new_window()
            self._turn_terms.append(turn_terms)
            self._turn_count = 1
            self._last_reference = resolved_text
        elif status == STATUS_FOLLOW_UP:
            if self._thread_id == 0:
                self._thread_id = 1
            self._turn_terms.append(turn_terms)
            self._turn_count += 1
            if resolved_text:
                self._last_reference = resolved_text

        self._topic = result.topic
        self._current = result
        self._thread = ConversationThreadState(
            self._thread_id, result.topic, status, self._turn_count,
            self._last_reference, self._thread_terms(),
        )
        return result

    def _new_window(self):
        return deque(maxlen=self.window)

    def _thread_terms(self):
        seen = []
        for terms in self._turn_terms:
            for term in terms:
                if term not in seen:
                    seen.append(term)
        return seen

    @property
    def topic(self):
        return self._topic

    @property
    def current(self):
        """The result of the most recent update() (an empty, topic-less
        result before any update or after reset())."""
        return self._current

    @property
    def thread(self):
        """The ConversationThreadState after the most recent update()."""
        return self._thread

    def reset(self):
        self._topic = None
        self._current = ActiveTopicResult(None, None, 0.0, False, None, "no_topic_yet")
        self._thread_id = 0
        self._turn_terms = self._new_window()
        self._turn_count = 0
        self._last_reference = None
        self._thread = ConversationThreadState(0, None, STATUS_ISOLATED, 0, None, [])
