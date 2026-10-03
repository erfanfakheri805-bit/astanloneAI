"""
Relation Phrasing
==================
Deterministic, natural-language phrasing for a stored (subject,
relation_type, object) triple - the single place that turns an
internal relationship-graph edge into a human-readable sentence
instead of a raw "SUBJECT RELATION_TYPE OBJECT" record dump.

Used by both the Reasoning Engine (reasoning/reasoning_engine.py, when
constructing an answer to a question) and Core (core/core.py, when
acknowledging what was just learned from a plain conversational
statement) - one shared formatter, not two competing ones, so a fact
is described the same way regardless of which path produced the
response.

This is plain template substitution, not natural-language generation:
each known relation type maps to a fixed sentence template. A relation
type with no specific template still gets a complete, readable
sentence via the generic fallback - never a raised exception, and
never the bare "SUBJECT RELATION_TYPE OBJECT" shape this module exists
to avoid.
"""

_TEMPLATES = {
    "IS_A": "{subject} is a {object}.",
    "IS_CALLED": "{subject} is called {object}.",
    "USES": "{subject} uses {object}.",
    "HAS": "{subject} has {object}.",
    "CONTAINS": "{subject} contains {object}.",
    "DEPENDS_ON": "{subject} depends on {object}.",
    "USED_FOR": "{subject} is used for {object}.",
}


def phrase(subject, relation_type, obj):
    """Return a natural-language sentence describing
    (subject, relation_type, obj). Falls back to a generic, still
    grammatical "<subject> <relation words> <object>." shape for any
    relation type without a specific template above - e.g. an
    AEL-defined custom relation type this module has never seen."""
    template = _TEMPLATES.get(relation_type)
    if template:
        return template.format(subject=subject, object=obj)
    return f"{subject} {relation_type.replace('_', ' ').lower()} {obj}."
