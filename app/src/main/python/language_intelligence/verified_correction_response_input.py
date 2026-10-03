"""
Language Intelligence - Verified Correction Response Input
========================================================================
Prompt 485. A small, deterministic, READ-ONLY structure that
represents ONE correction result which has already been applied and
confirmed usable by the EXISTING correction-application flow (Prompt
474/478/479 `CorrectionApplicationResult`, Prompt 480
`validate_applied_correction_result()`, Prompt 482
`verify_correction_application_result()`, Prompt 484
`is_correction_application_result_usable()`). This module adds ONLY
the input structure itself - no matching, no correction application,
no text modification, and no response-generation integration happens
here.

    apply_correction_request_with_validation(...)   (Prompt 477, unchanged)
        -> CorrectionApplicationResult
    is_correction_application_result_usable(...)     (Prompt 484, unchanged)
        -> True / False
    VerifiedCorrectionResponseInput(...)             (THIS module)

This module performs no lookup, matching, ranking, or correction logic
of its own - it only holds six already-known values in one small,
flat, read-only structure, the SAME "wrap already-known values as a
small, flat, read-only structure" posture
`correction_application_candidate.py` (Prompt 470) and
`correction_application_request.py` (Prompt 473) already use.

Represents ONLY an already-applied correction
------------------------------------------------------------
Unlike `CorrectionApplicationCandidate` / `CorrectionApplicationRequest`
(which carry an `is_valid` flag and accept an "empty, not valid"
placeholder state), a `VerifiedCorrectionResponseInput` has no such
placeholder state - it exists only to represent a correction that has
ALREADY been verified usable. Construction itself is the gate:
supplying data that does not meet every requirement below raises
`ValueError` rather than producing a half-populated or `is_valid=False`
instance - the SAME "required field missing/invalid -> raise" posture
`CorrectionApplicationResult.__init__` (Prompt 474) already uses for
its own `status` field, generalized here to every field this structure
carries.

Fields (only these six; nothing else is carried)
----------------------------------------------------
    text_before        the exact target text before the correction -
                        required, non-blank.
    text_after          the exact target text after the correction -
                        required, non-blank.
    matched_text        the exact original expression that was matched
                        - required, non-blank.
    replacement_text    the exact corrected expression that was
                        inserted in place of `matched_text` - required,
                        non-blank.
    match_count         the number of exact occurrences that were
                        replaced - required, an `int` greater than
                        zero.
    metadata            a small, optional, JSON-shaped dict of
                        additional detail; `{}` when not supplied.
                        Deep-copied at construction time and again by
                        `to_dict()`/`copy()`, the SAME
                        `copy.deepcopy()` convention
                        `CorrectionApplicationResult.metadata` already
                        uses for its own mutable, caller-shaped field.

Exact strings, never normalized
------------------------------------
`text_before`, `text_after`, `matched_text`, and `replacement_text`
are stored and returned EXACTLY as given - never stripped, cased,
trimmed, or otherwise transformed. `_is_blank()`
(correction_understanding.py, imported, never re-implemented) is used
ONLY to decide whether construction should raise; it never changes
what is actually stored. Blank means `None`, an empty string, or a
whitespace-only string - the SAME "nothing supplied" rule
`correction_lookup_usability.py` (Prompt 468) already applies to its
own required-field pair.

Never applies, matches, or generates anything
-------------------------------------------------
`VerifiedCorrectionResponseInput` never performs correction
application, never performs matching (fuzzy, semantic, embeddings,
spelling-correction, normalization, guessing, ranking, or
confidence-based), never modifies the original text, never triggers
response generation, and never automatically obtains or creates a
correction. Building an instance from six already-known values is the
entire operation.

Read-only and non-mutating
-----------------------------
Only `metadata` can carry a mutable, caller-shaped value; it is
deep-copied at construction time, so mutating the dict passed in never
reaches back into this structure. `to_dict()` and `copy()` each return
a fresh, independent structure/deep copy on every call - the SAME
"never hand back shared mutable state" posture already used throughout
this package. The same six inputs always produce an equal instance.

Not yet connected
--------------------
This module does not modify `CorrectionApplicationResult`
(correction_application_result.py), does not modify
`ResponseGenerationContext` (response_generation_context.py), and is
not wired into the normal response-generation pipeline. It does not
touch Learning, Memory, Knowledge, Meaning Resolution, Correction
Understanding, Correction Lookup, Correction Selection, Correction
Application, Correction Application Validation, Correction Application
Verification, the Local Model Runtime, `AgentLoop`, or Self-Upgrade -
deciding when/how a `VerifiedCorrectionResponseInput` is built from a
verified `CorrectionApplicationResult`, and what response generation
eventually does with one, are both separate, future, explicitly scoped
steps.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
"""

import copy

from language_intelligence.correction_understanding import _is_blank


class VerifiedCorrectionResponseInput:
    """The minimum useful fields describing one already-verified,
    already-applied correction - nothing more. See the module
    docstring for the exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`, `copy()`, and `from_dict()`. Never
    applies, matches, or generates anything - see the module
    docstring. Construction raises `ValueError` for any missing or
    invalid required field; there is no "empty, not valid" placeholder
    state - see "Represents ONLY an already-applied correction" above.
    """

    __slots__ = (
        "text_before", "text_after", "matched_text", "replacement_text",
        "match_count", "metadata",
    )

    def __init__(self, text_before, text_after, matched_text,
                 replacement_text, match_count, metadata=None):
        if _is_blank(text_before):
            raise ValueError("text_before must not be blank")
        if _is_blank(text_after):
            raise ValueError("text_after must not be blank")
        if _is_blank(matched_text):
            raise ValueError("matched_text must not be blank")
        if _is_blank(replacement_text):
            raise ValueError("replacement_text must not be blank")
        if not isinstance(match_count, int) or match_count <= 0:
            raise ValueError("match_count must be an int greater than zero")

        self.text_before = text_before
        self.text_after = text_after
        self.matched_text = matched_text
        self.replacement_text = replacement_text
        self.match_count = match_count
        self.metadata = copy.deepcopy(metadata) if metadata else {}

    def to_dict(self):
        """This input as a plain, JSON-shaped dict - the same
        `to_dict()` convention this package's other result/input
        models already follow (e.g. `CorrectionApplicationResult`,
        `CorrectionApplicationCandidate`). `metadata` is deep-copied
        again here, so mutating the returned dict never reaches back
        into this instance."""
        return {
            "text_before": self.text_before,
            "text_after": self.text_after,
            "matched_text": self.matched_text,
            "replacement_text": self.replacement_text,
            "match_count": self.match_count,
            "metadata": copy.deepcopy(self.metadata),
        }

    def copy(self):
        """Return a new, independent `VerifiedCorrectionResponseInput`
        with the same six fields (`self.copy() == self`). The SAME
        "deep-copy the one mutable field, pass everything else
        through" convention `CorrectionApplicationCandidate.copy()`
        (Prompt 470) already follows. Never mutates `self`."""
        return VerifiedCorrectionResponseInput(
            text_before=self.text_before,
            text_after=self.text_after,
            matched_text=self.matched_text,
            replacement_text=self.replacement_text,
            match_count=self.match_count,
            metadata=copy.deepcopy(self.metadata),
        )

    def __eq__(self, other):
        if not isinstance(other, VerifiedCorrectionResponseInput):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "VerifiedCorrectionResponseInput(%r)" % (self.to_dict(),)

    @classmethod
    def from_dict(cls, data):
        """Reconstruct a `VerifiedCorrectionResponseInput` from a
        plain dict shaped like `to_dict()`'s output - the SAME
        `__init__`/keyword-argument reconstruction convention
        `CorrectionFeedbackRecord.from_dict()` already uses.

        `data` must be a dict; anything else raises `TypeError` - the
        SAME "isinstance check, then raise" posture used throughout
        this package. `data` is never mutated. Required fields
        (`text_before`, `text_after`, `matched_text`,
        `replacement_text`, `match_count`) are taken exactly as given
        - a `data` missing one of them raises `TypeError` from
        `__init__` itself (Python's own "missing required argument"
        behavior); a `data` carrying an invalid value for one of them
        raises `ValueError` from `__init__` exactly as direct
        construction does. `metadata` falls back to `__init__`'s own
        default (`None` -> `{}`) when absent from `data`, the same
        defaulting a direct caller who omits it already gets.
        """
        if not isinstance(data, dict):
            raise TypeError("data must be a dict")
        return cls(**data)


def build_verified_correction_response_input(
        text_before, text_after, matched_text, replacement_text,
        match_count, metadata=None):
    """Build a `VerifiedCorrectionResponseInput` from six already-known
    values - the SAME "one small, focused builder function next to the
    structure it builds" convention this package already uses (e.g.
    `build_correction_application_candidate()`,
    `build_correction_application_request()`). Adds no logic beyond
    `VerifiedCorrectionResponseInput.__init__` itself: invalid data
    raises exactly the same `ValueError` construction already raises.
    Provided so a future, separately-scoped step can build one without
    naming the class directly, the same convenience the other
    `build_*` functions in this package already offer.
    """
    return VerifiedCorrectionResponseInput(
        text_before=text_before,
        text_after=text_after,
        matched_text=matched_text,
        replacement_text=replacement_text,
        match_count=match_count,
        metadata=metadata,
    )
