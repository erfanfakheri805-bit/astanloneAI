"""
Understanding Engine - Entity / Term Candidate Extraction
=============================================================
Extracts candidate concept names from a sentence, for example
"Python" and "programming language" from
"Python is a programming language.".

This module makes an explicit distinction the rest of the system
relies on: everything returned here is a *candidate* entity - a
string worth checking against (or later teaching into) the Knowledge
Graph - never a *confirmed* concept. Confirming a candidate against
what the application actually knows is the Knowledge System's job
(see core.py:_find_best_known_concept), and deciding whether an
unconfirmed candidate should become new permanent knowledge is the
Learning Engine's job (see learning/learning_system.py). This module
does neither.

Two sources of candidates are used, in order of preference:

1. If relation candidates were already found for this sentence (see
   relation_extraction.py), their subject/object terms are the
   cleanest available candidates - "Python" and "programming language"
   rather than every individual word.
2. Otherwise, fall back to the existing single-word extraction in
   term_extraction.py (already used by core.py for knowledge lookups),
   with command verbs additionally filtered out for command sentences
   so "Teach me Python." yields "python", not "teach"+"python".
"""

from .term_extraction import extract_candidate_terms
from .sentence_analysis import COMMAND_VERBS_EN, COMMAND_VERBS_FA, POLITENESS_WORDS, SENTENCE_COMMAND

STATUS_CANDIDATE = "candidate"

_ALL_COMMAND_VERBS = COMMAND_VERBS_EN | COMMAND_VERBS_FA | POLITENESS_WORDS


def extract_entities(normalized_text, sentence_type, relation_candidates):
    """Return a list of {"text": str, "status": "candidate"} dicts.
    Order is first-seen, de-duplicated case-insensitively."""
    seen = set()
    entities = []

    def add(term):
        term = (term or "").strip()
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            entities.append({"text": term, "status": STATUS_CANDIDATE})

    for candidate in relation_candidates:
        add(candidate.subject)
        add(candidate.object)

    if not entities and normalized_text:
        for term in extract_candidate_terms(normalized_text):
            if sentence_type == SENTENCE_COMMAND and term in _ALL_COMMAND_VERBS:
                continue
            add(term)

    return entities
