"""
Understanding / Analysis - Term Extraction
============================================
The target architecture calls for a distinct Understanding/Analysis
stage between the Parser and the Learning/Reasoning engines. This is a
deliberately small, honest slice of that stage: turning a free-text
conversational message into an ordered list of candidate terms worth
checking against the Knowledge Graph.

This is NOT natural-language understanding. It does no part-of-speech
tagging, parsing, or entity recognition beyond "split into words, drop
common stopwords, keep the rest in first-seen order, without
duplicates." It exists because a plain substring search over the whole
message (KnowledgeSystem.search()) only matches when the concept name
happens to appear verbatim as a phrase inside a stored name/description -
it cannot find "indentation" inside "tell me about indentation". This
module is what lets Core check individual meaningful words from a
sentence against what it actually knows, instead of only the sentence
as a whole.
"""

import re

# A small, generic English stopword list - just common words that would
# otherwise crowd out the actual subject of a sentence. Deliberately not
# exhaustive and not language-general; this is a heuristic filter for the
# foundation stage, not a linguistic model.
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "tell", "me", "about", "what", "whats", "who", "which", "when", "where",
    "why", "how", "do", "does", "did", "doing", "you", "your", "yours", "i",
    "im", "to", "of", "in", "on", "for", "and", "or", "with", "this", "that",
    "these", "those", "please", "can", "could", "would", "should", "know",
    "explain", "describe", "some", "any", "it", "its", "we", "us", "my",
}

_WORD_RE = re.compile(r"[A-Za-z0-9_']+")


def extract_candidate_terms(text):
    """Return candidate concept-name terms from `text`: lowercased words,
    in first-seen order, with stopwords and duplicates removed."""
    seen = set()
    terms = []
    for match in _WORD_RE.finditer(text.lower()):
        word = match.group()
        if word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        terms.append(word)
    return terms
