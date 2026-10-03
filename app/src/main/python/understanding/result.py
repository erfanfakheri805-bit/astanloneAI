"""
Understanding Engine - Structured Result
===========================================
`UnderstandingResult` is the single structured object the Understanding
Engine produces and the Learning Engine (or anything else) consumes.
It is the "STRUCTURED UNDERSTANDING RESULT" box in the pipeline:

    USER INPUT -> ... -> STRUCTURED UNDERSTANDING RESULT -> LEARNING ENGINE

Nothing in this stage writes to permanent storage - this object is
purely a description of what the Understanding Engine noticed. `facts`
is intentionally always empty at this stage; it exists as a stable
field name for a later stage where *confirmed* (not merely candidate)
facts would be attached, without needing to change this class's shape
again.

`context_resolutions` is populated only when `understand()` was given
a conversational context (see understanding/engine.py and
context/reference_resolution.py): a list of structured
ReferenceResolution.to_dict() traces - one per reference (e.g. "it",
"the language") the CONTEXT RESOLUTION step attempted to resolve
against recent context, confident or not. `entities`/`relations` above
already reflect any confident resolutions (e.g. "Python" in place of
"it"); this field exists purely for inspection/debugging of *how* that
happened, not as a second copy of the result.

`correction_candidate` - Prompt 440: a `correction_detection.
CorrectionCandidate.to_dict()` (`original_expression`,
`corrected_expression`) when the fixed, explicit correction marker
`correction_detection.detect_explicit_correction()` recognizes was
found in `normalized_text`; `None` otherwise (the ordinary, unchanged
case for every message that is not that one explicit marker). This is
a raw candidate only - no status, no language/locale/confidence
judgement; `language_intelligence.correction_understanding.
build_correction_understanding()` (Prompt 439) is what turns it into a
structured result, one layer up.
"""


class UnderstandingResult:
    def __init__(
        self,
        original_text,
        normalized_text,
        language,
        tokens,
        sentence_type,
        entities,
        relations,
        confidence,
        warnings=None,
        facts=None,
        context_resolutions=None,
        correction_candidate=None,
    ):
        self.original_text = original_text
        self.normalized_text = normalized_text
        self.language = language
        self.tokens = tokens                    # list[nl_tokenizer.Token]
        self.sentence_type = sentence_type
        self.entities = entities                # list[{"text", "status"}]
        self.relations = relations              # list[RelationCandidate]
        self.facts = facts if facts is not None else []  # reserved for a later stage
        self.confidence = confidence
        self.warnings = warnings if warnings is not None else []
        # list[dict] - see class docstring above.
        self.context_resolutions = context_resolutions if context_resolutions is not None else []
        # dict (CorrectionCandidate.to_dict()) or None - see class
        # docstring's `correction_candidate` entry above (Prompt 440).
        self.correction_candidate = correction_candidate

    def __repr__(self):
        return (
            f"UnderstandingResult(sentence_type={self.sentence_type!r}, "
            f"language={self.language!r}, entities={len(self.entities)}, "
            f"relations={len(self.relations)}, confidence={self.confidence:.2f})"
        )

    def to_dict(self):
        return {
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "language": self.language,
            "tokens": [t.to_dict() for t in self.tokens],
            "sentence_type": self.sentence_type,
            "entities": self.entities,
            "relations": [r.to_dict() for r in self.relations],
            "facts": self.facts,
            "confidence": round(self.confidence, 4),
            "warnings": self.warnings,
            "context_resolutions": self.context_resolutions,
            "correction_candidate": self.correction_candidate,
        }
