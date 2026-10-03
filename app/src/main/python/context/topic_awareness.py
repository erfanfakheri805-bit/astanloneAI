"""
Conversation Context - Topic-Aware Response Decision (Prompt 394)
===================================================================
Prompt 393 tracks the active topic (context/active_topic.py). This
module is the small, deterministic step that lets that topic take part
in Response Construction: given the four separate inputs a reply is
built from -

    1. the original user input            (never altered here)
    2. the relevant conversation context  (context/relevance.py)
    3. the resolved reference             (message_reference_resolution.py)
    4. the active topic                   (context/active_topic.py)

- it decides whether the current message is *clearly a continuation of
the active topic*, and if so which verbatim earlier user statement
supports that. Core._construct_fallback_reply reads the result and
shapes the reply from it; the result is also recorded in
`Core.last_response_context["topic_awareness"]` so the decision is
observable.

The topic is CONTEXT, not knowledge. This module never produces any
information about the topic: the only content it can hand back is
`supporting_context`, a turn the user themselves said (verbatim).
Knowing the topic is "robot game" says nothing about its mechanics,
characters or weapons.

A message is topic-aware only when ALL hold:
  - an active topic exists;
  - the reference (if any) is not ambiguous - an ambiguous reference
    means we do not know what the message points at, so no connection
    is invented;
  - the message is not a verbatim repeat of something the user already
    said (repeating a sentence is not following up on it);
  - the tracker judged this message a *continuation* (topic kept for a
    positive reason: shared words, an on-topic relevant turn, a
    matching resolved reference, or a request whose subject is deferred
    to context) - not the message that introduced the topic, not a
    change of subject, and not a contentless message ("Okay.").
"""

from understanding.normalization import normalize
from .active_topic import SOURCE_RESOLVED_REFERENCE

_CONTINUATION_REASONS = {
    "shares_terms_with_topic": "shared_terms",
    "relevant_context_on_topic": "relevant_context",
    "reference_matches_current_topic": "resolved_reference",
    "topic_from_resolved_reference": "resolved_reference",
    "dependent_request_on_topic": "dependent_request",
    "shares_terms_with_thread": "thread_terms",
    "elliptical_follow_up": "elliptical_follow_up",
}


class TopicAwareness:
    """Structured decision. `topic_aware` False means Response
    Construction behaves exactly as it did before Prompt 394; `reason`
    then says why. `supporting_context` is a verbatim earlier user
    statement, or None - never a paraphrase or a guess."""

    def __init__(self, topic_aware, topic, basis, supporting_context, reason):
        self.topic_aware = topic_aware
        self.topic = topic
        self.basis = basis
        self.supporting_context = supporting_context
        self.reason = reason

    def __repr__(self):
        return (
            f"TopicAwareness(topic_aware={self.topic_aware}, topic={self.topic!r}, "
            f"basis={self.basis!r}, reason={self.reason!r})"
        )

    def to_dict(self):
        return {
            "topic_aware": self.topic_aware,
            "topic": self.topic,
            "basis": self.basis,
            "supporting_context": self.supporting_context,
            "reason": self.reason,
        }


def _not_aware(reason):
    return TopicAwareness(False, None, None, None, reason)


def _supporting_context(topic, relevant_context, resolved_reference):
    """The verbatim user statement that best backs the topic: the
    resolved referent when the reference resolved, otherwise the
    highest-ranked selected turn sharing a word with the topic. Never
    a question."""
    if (resolved_reference is not None and resolved_reference.has_reference
            and not resolved_reference.ambiguous and resolved_reference.resolved_context):
        return resolved_reference.resolved_context
    topic_words = set(topic.split())
    selected = list(relevant_context.selected) if relevant_context is not None else []
    for item in sorted(selected, key=lambda i: i["rank"]):
        user_text = (item.get("turn") or {}).get("user") or ""
        if user_text.strip().endswith("?"):
            continue
        if topic_words & set(user_text.lower().replace(".", " ").replace(",", " ").split()):
            return user_text
    return None


def assess_topic_awareness(current_input, relevant_context, resolved_reference, active_topic):
    """Decide whether the reply to `current_input` should be
    topic-aware. Pure and read-only: never raises, never mutates an
    argument, never returns anything the user did not say."""
    if active_topic is None or not active_topic.topic:
        return _not_aware("no_active_topic")
    if resolved_reference is not None and resolved_reference.has_reference and resolved_reference.ambiguous:
        return _not_aware("ambiguous_reference")
    current = normalize(current_input or "").normalized_text.lower()
    selected = list(relevant_context.selected) if relevant_context is not None else []
    for item in selected:
        earlier = normalize((item.get("turn") or {}).get("user") or "").normalized_text.lower()
        if current and current == earlier:
            return _not_aware("repeat_of_earlier_message")
    basis = _CONTINUATION_REASONS.get(active_topic.reason)
    if basis is None:
        return _not_aware("not_a_continuation:" + str(active_topic.reason))
    if active_topic.changed and active_topic.topic_source != SOURCE_RESOLVED_REFERENCE:
        return _not_aware("topic_changed")
    support = _supporting_context(active_topic.topic, relevant_context, resolved_reference)
    return TopicAwareness(True, active_topic.topic, basis, support, "continuation:" + basis)
