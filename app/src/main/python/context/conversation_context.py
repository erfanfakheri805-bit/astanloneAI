"""
Conversation Context
======================
Bounded, in-memory, short-term conversational state - the "CONVERSATION
CONTEXT" box in the pipeline this stage introduces:

    USER INPUT -> CONVERSATION CONTEXT -> UNDERSTANDING ENGINE
        -> CONTEXT RESOLUTION -> STRUCTURED UNDERSTANDING RESULT
        -> LEARNING ENGINE -> KNOWLEDGE / MEMORY

`ConversationContext` is deliberately separate from, and never a
replacement for, the project's persistent storage
(memory/memory_system.py, knowledge/knowledge_system.py,
concepts/concept_system.py):

    SHORT-TERM CONTEXT (this module)   PERSISTENT KNOWLEDGE/MEMORY
    ---------------------------------  ---------------------------------
    recent conversation                learned concepts
    temporary references               stable facts / relationships
    current task context               validated information
    lives only in this process's RAM   lives in the sqlite-backed stores
    bounded size, oldest evicted       unbounded, never evicted here

Nothing in this module ever calls into memory/knowledge/concepts - see
core/core.py for how the two are wired together (context is populated
alongside, not instead of, persistent learning) and reset() below for
why clearing context can never touch persistent storage: it simply
has no reference to it to begin with.

Two things are kept, both bounded by the same `max_size`:

    ENTRIES  one ContextEntry per Understanding Engine call (entities/
             relations - what reference resolution reads). Written by
             Core.understand()/learn_from_text(), so a message that never
             reaches the Understanding Engine (an AEL command, a goal
             request, a skill-matched greeting) produces none.
    TURNS    one {"user", "assistant"} pair per message Core.process_input()
             handled, whichever path handled it - the plain
             "what was just said, and what did I reply" record. Entries
             have no slot for the assistant's reply and don't exist for
             every path, so replies are kept here rather than bolted onto
             them (which would attach a reply to the wrong entry).
             relevance.py picks which of these turns bear on a message.

Bounded via a plain FIFO window (oldest entry evicted first once the
configured size is reached). Recency is itself the "least useful"
signal for *this* stage - the entries most likely to be needed for
resolving an upcoming reference are the most recent ones - so a plain
recency-bounded window meets the spec's "remove the least useful recent
entries" requirement without inventing a separate relevance model on
top of the deterministic `importance` score (which is still recorded
per-entry, for callers/future stages that want to weigh entries rather
than just keep-or-drop them).
"""

import itertools
from collections import deque

from .context_entry import ContextEntry
from .importance import compute_importance

DEFAULT_CONTEXT_SIZE = 10


class ConversationContext:
    """Not thread-safe (matches the rest of the project - Core itself
    assumes single-threaded request handling); safe to use one instance
    per Core / per conversation session."""

    def __init__(self, max_size=DEFAULT_CONTEXT_SIZE):
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self.max_size = max_size
        self._entries = deque(maxlen=max_size)
        self._turns = deque(maxlen=max_size)
        self._id_counter = itertools.count(1)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------
    def add_understanding(self, understanding_result, source="conversation",
                           importance=None, learning_summary=None):
        """Record one UnderstandingResult as a new ContextEntry and
        return it. `understanding_result.relations`/`.entities` are
        stored in their already-serializable `.to_dict()` shape (see
        context_entry.py) - this method never keeps a live reference to
        Understanding Engine objects."""
        if importance is None:
            importance = compute_importance(understanding_result)

        entry = ContextEntry(
            entry_id=next(self._id_counter),
            input_text=understanding_result.original_text,
            normalized_text=understanding_result.normalized_text,
            language=understanding_result.language,
            sentence_type=understanding_result.sentence_type,
            entities=list(understanding_result.entities),
            relations=[r.to_dict() for r in understanding_result.relations],
            confidence=understanding_result.confidence,
            importance=importance,
            source=source,
            learning_summary=learning_summary,
        )
        self._entries.append(entry)
        return entry

    def annotate_last(self, learning_summary):
        """Attach a learning-operation summary to the most recently
        added entry, if any. Used by Core.learn_from_text() to record
        "recent learning operations" onto the entry that triggered
        them, without the Understanding Engine needing to know the
        Learning Engine exists. No-op if context is empty."""
        if self._entries:
            self._entries[-1].learning_summary = learning_summary

    def add_turn(self, user_text, assistant_text):
        """Record one completed exchange: what the user said and what
        the assistant replied. Called once per handled message by
        Core.process_input(). Oldest turn is evicted once `max_size`
        turns are held. Nothing here is persisted."""
        self._turns.append({"user": user_text, "assistant": assistant_text})

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def recent_entries(self, limit=None):
        """Return recent ContextEntry objects, oldest-first (matching
        the order they occurred in). Internal/engine-facing - prefer
        get_recent_context() for anything crossing a module boundary,
        since that returns plain dicts instead of live objects."""
        entries = list(self._entries)
        if limit is not None:
            entries = entries[-limit:]
        return entries

    def get_recent_context(self, limit=None):
        """Structured (not merely formatted-text) view of recent
        context, per the spec's context-inspection requirement. Safe to
        hand to a UI, a test, or a future reasoning/planning engine."""
        return [e.to_dict() for e in self.recent_entries(limit)]

    def get_recent_turns(self, limit=None):
        """Recent {"user", "assistant"} turns, oldest-first. Returns
        copies, so a caller can't alter what the context holds. `limit`
        keeps only the most recent N (0 or less -> none)."""
        turns = [dict(t) for t in self._turns]
        if limit is not None:
            turns = turns[-limit:] if limit > 0 else []
        return turns

    def __len__(self):
        return len(self._entries)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------
    def reset(self):
        """Clear short-term conversational context only. This method
        has no access to memory/knowledge/concepts and therefore cannot
        delete persistent knowledge even by mistake - see module
        docstring."""
        self._entries.clear()
        self._turns.clear()
