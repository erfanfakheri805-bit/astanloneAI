"""
Understanding Engine - Basic Sentence Type Detection
======================================================
Classifies a normalized sentence as one of: "statement", "question",
"command", or "unknown". This is a small, deterministic heuristic -
not a part-of-speech tagger or a trained classifier:

1. Text ending in "?" (or the Persian "؟") is a question, full stop.
2. Otherwise, if the first meaningful word is a known question word
   ("what", "who", "چیست", ...) it's a question.
3. Otherwise, if the first meaningful word is a known command/imperative
   verb ("teach", "explain", "بگو", ...) it's a command.
4. Otherwise, if there is at least one recognizable word, it's a
   statement.
5. Empty input, or input with no recognizable words at all, is
   "unknown".

The word lists below are intentionally small and are shared with
entity_extraction.py (so a command verb like "teach" is not
mistakenly treated as the subject of the sentence).
"""

from .nl_tokenizer import TOKEN_WORD, TOKEN_PUNCT
from .language_detection import LANGUAGE_PERSIAN

SENTENCE_STATEMENT = "statement"
SENTENCE_QUESTION = "question"
SENTENCE_COMMAND = "command"
SENTENCE_UNKNOWN = "unknown"

QUESTION_WORDS_EN = {
    "what", "whats", "who", "whom", "whose", "which", "when", "where",
    "why", "how", "is", "are", "do", "does", "did", "can", "could",
    "would", "should", "will", "am",
}

QUESTION_WORDS_FA = {
    "چیست", "چی", "کیست", "کجا", "چرا", "چگونه", "آیا", "کدام", "چند",
}

COMMAND_VERBS_EN = {
    "teach", "tell", "show", "explain", "give", "list", "find",
    "create", "make", "define", "describe", "help", "remember",
}

COMMAND_VERBS_FA = {
    "یاد", "بگو", "نشان", "توضیح", "بده", "بساز", "کمک",
}

# Prompt 630: leading politeness/greeting words are not the request
# itself. "Please explain recursion" is a command and "Hey, what is
# Python" is a question; without skipping the prefix both were read as
# plain statements because the first word was neither a question word
# nor a command verb.
POLITENESS_WORDS_EN = {"please", "kindly", "pls", "plz"}
POLITENESS_WORDS_FA = {"لطفا", "لطفاً", "لطفآ"}
GREETING_WORDS_EN = {"hey", "hi", "hello"}
POLITENESS_WORDS = POLITENESS_WORDS_EN | POLITENESS_WORDS_FA
# "Please is a word." is a statement about the word, not a request.
_COPULAS = {"is", "are", "was", "were"}

_QUESTION_MARKS = ("?", "؟")


def _leading_request_words(tokens):
    """Words of `tokens` with a leading run of politeness words, and a
    greeting directly followed by a comma, removed. Falls back to the
    unstripped words if nothing would remain, so input made only of
    such words keeps its previous classification."""
    seq = [t for t in tokens if t.type in (TOKEN_WORD, TOKEN_PUNCT)]
    i = 0
    while i < len(seq):
        tok = seq[i]
        if tok.type != TOKEN_WORD:
            break
        w = tok.value.lower()
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        if w in POLITENESS_WORDS and not (
                nxt is not None and nxt.type == TOKEN_WORD
                and nxt.value.lower() in _COPULAS):
            i += 1
        elif (w in GREETING_WORDS_EN) and nxt is not None \
                and nxt.type == TOKEN_PUNCT and nxt.value == ",":
            i += 2
        else:
            break
    stripped = [t.value.lower() for t in seq[i:] if t.type == TOKEN_WORD]
    if stripped:
        return stripped
    return [t.value.lower() for t in tokens if t.type == TOKEN_WORD]


def detect_sentence_type(normalized_text, tokens, language):
    """`tokens` should be the result of nl_tokenizer.tokenize() on the
    same `normalized_text`; `language` should come from
    language_detection.detect_language()."""
    if not normalized_text:
        return SENTENCE_UNKNOWN

    if normalized_text.rstrip().endswith(_QUESTION_MARKS):
        return SENTENCE_QUESTION

    words = _leading_request_words(tokens)
    if not words:
        return SENTENCE_UNKNOWN

    first = words[0]
    question_words = QUESTION_WORDS_FA if language == LANGUAGE_PERSIAN else QUESTION_WORDS_EN
    command_verbs = COMMAND_VERBS_FA if language == LANGUAGE_PERSIAN else COMMAND_VERBS_EN

    if first in question_words:
        return SENTENCE_QUESTION
    if first in command_verbs:
        return SENTENCE_COMMAND

    return SENTENCE_STATEMENT
