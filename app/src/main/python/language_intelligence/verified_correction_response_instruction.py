"""
Language Intelligence - Verified Correction Response Instruction
========================================================================
Prompt 490. A small, deterministic, READ-ONLY structure that
represents ONE instruction telling the response-generation layer that
a verified correction is available and that the corrected form should
be used. This module adds ONLY the instruction structure itself - no
response text is modified, no matching happens here, and this
instruction is not connected to the normal response-generation flow.

    VerifiedCorrectionResponseInput          (Prompt 485, unchanged)
    is_verified_correction_response_input_usable(...)   (Prompt 488, unchanged)
    extract_usable_verified_correction_response_input(...)   (Prompt 489, unchanged)
        -> VerifiedCorrectionResponseInput copy, or None
    VerifiedCorrectionResponseInstruction    (THIS module)

This module performs no correction application, no matching (fuzzy,
semantic, embeddings, spelling-correction, normalization, guessing,
ranking, or confidence-based), no response text generation, and no
response text modification - it only holds six already-known values
in one small, flat, read-only structure, the SAME "wrap already-known
values as a small, flat, read-only structure" posture
`verified_correction_response_input.py` (Prompt 485) and
`correction_application_candidate.py` (Prompt 470) already use.

Represents ONLY a deterministic instruction to use a corrected form
------------------------------------------------------------------------
Like `VerifiedCorrectionResponseInput` (Prompt 485), a
`VerifiedCorrectionResponseInstruction` has no "empty, not valid"
placeholder state - it exists only to represent one already-decided
instruction. Construction itself is the gate: supplying data that
does not meet every requirement below raises `ValueError` rather than
producing a half-populated instance - the SAME "required field
missing/invalid -> raise" posture `VerifiedCorrectionResponseInput.
__init__` already uses, generalized here to this structure's own six
fields.

Fields (only these six; nothing else is carried)
----------------------------------------------------
    source_text        the exact text the correction applies to -
                        required, non-blank.
    corrected_text      the exact text after the correction is used -
                        required, non-blank.
    matched_text        the exact original expression that was
                        matched - required, non-blank.
    replacement_text    the exact corrected expression that replaces
                        `matched_text` - required, non-blank.
    match_count         the number of exact occurrences the
                        instruction covers - required, an `int`
                        greater than zero.
    instruction_type     the kind of instruction this is - required;
                        currently only `INSTRUCTION_TYPE_USE_CORRECTED_TEXT`
                        (`"USE_CORRECTED_TEXT"`) is supported. Any
                        other value raises `ValueError` - never
                        silently accepted, never guessed at.

Exact strings, never normalized
------------------------------------
`source_text`, `corrected_text`, `matched_text`, and `replacement_text`
are stored and returned EXACTLY as given - never stripped, cased,
trimmed, or otherwise transformed. `_is_blank()`
(correction_understanding.py, imported, never re-implemented) is used
ONLY to decide whether construction should raise; it never changes
what is actually stored - the SAME convention
`VerifiedCorrectionResponseInput` already uses for its own four text
fields.

Never applies, matches, or generates anything
-------------------------------------------------
`VerifiedCorrectionResponseInstruction` never performs correction
application, never performs matching of any kind, never modifies any
response text, and never triggers response generation. Building an
instance from six already-known values is the entire operation.

Read-only and non-mutating
-----------------------------
`to_dict()` and `copy()` each return a fresh, independent
structure/copy on every call - the SAME "never hand back shared
mutable state" posture `VerifiedCorrectionResponseInput.to_dict()` /
`.copy()` already use. The same six inputs always produce an equal
instance.

Not yet connected
--------------------
This module does not modify `VerifiedCorrectionResponseInput`
(verified_correction_response_input.py),
`is_verified_correction_response_input_usable()`
(verified_correction_response_input_usability.py),
`extract_usable_verified_correction_response_input()`
(verified_correction_response_input_extraction.py), or
`ResponseGenerationContext` (response_generation_context.py), and is
not wired into the normal response-generation pipeline. It does not
touch Learning, Memory, Knowledge, Meaning Resolution, Correction
Understanding, Correction Lookup, Correction Selection, Correction
Application, Correction Application Validation, Correction Application
Verification, `CorrectionApplicationResult`, the Local Model Runtime,
`AgentLoop`, or Self-Upgrade - deciding when/how a
`VerifiedCorrectionResponseInstruction` is built from an extracted
`VerifiedCorrectionResponseInput`, and what response generation
eventually does with one, are both separate, future, explicitly
scoped steps.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.
"""

from language_intelligence.correction_understanding import _is_blank

# The one currently-supported instruction_type value - see the module
# docstring's "instruction_type" field entry. Any other value raises
# ValueError at construction time; never a second, silently-accepted
# value.
INSTRUCTION_TYPE_USE_CORRECTED_TEXT = "USE_CORRECTED_TEXT"

_VALID_INSTRUCTION_TYPES = (INSTRUCTION_TYPE_USE_CORRECTED_TEXT,)


class VerifiedCorrectionResponseInstruction:
    """The minimum useful fields describing one deterministic
    instruction to use a verified correction's corrected form -
    nothing more. See the module docstring for the exact meaning of
    each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`, `copy()`, and `from_dict()`. Never
    applies, matches, or generates anything - see the module
    docstring. Construction raises `ValueError` for any missing or
    invalid required field; there is no "empty, not valid" placeholder
    state - see "Represents ONLY a deterministic instruction to use a
    corrected form" above.
    """

    __slots__ = (
        "source_text", "corrected_text", "matched_text", "replacement_text",
        "match_count", "instruction_type",
    )

    def __init__(self, source_text, corrected_text, matched_text,
                 replacement_text, match_count,
                 instruction_type=INSTRUCTION_TYPE_USE_CORRECTED_TEXT):
        if _is_blank(source_text):
            raise ValueError("source_text must not be blank")
        if _is_blank(corrected_text):
            raise ValueError("corrected_text must not be blank")
        if _is_blank(matched_text):
            raise ValueError("matched_text must not be blank")
        if _is_blank(replacement_text):
            raise ValueError("replacement_text must not be blank")
        if not isinstance(match_count, int) or match_count <= 0:
            raise ValueError("match_count must be an int greater than zero")
        if instruction_type not in _VALID_INSTRUCTION_TYPES:
            raise ValueError(
                "instruction_type must be one of %r" % (_VALID_INSTRUCTION_TYPES,)
            )

        self.source_text = source_text
        self.corrected_text = corrected_text
        self.matched_text = matched_text
        self.replacement_text = replacement_text
        self.match_count = match_count
        self.instruction_type = instruction_type

    def to_dict(self):
        """This instruction as a plain, JSON-shaped dict - the same
        `to_dict()` convention this package's other result/input
        models already follow (e.g. `VerifiedCorrectionResponseInput`,
        `CorrectionApplicationResult`)."""
        return {
            "source_text": self.source_text,
            "corrected_text": self.corrected_text,
            "matched_text": self.matched_text,
            "replacement_text": self.replacement_text,
            "match_count": self.match_count,
            "instruction_type": self.instruction_type,
        }

    def copy(self):
        """Return a new, independent `VerifiedCorrectionResponseInstruction`
        with the same six fields (`self.copy() == self`). The SAME
        "return an independent copy, never hand back shared mutable
        state" convention `VerifiedCorrectionResponseInput.copy()`
        already follows. Never mutates `self`."""
        return VerifiedCorrectionResponseInstruction(
            source_text=self.source_text,
            corrected_text=self.corrected_text,
            matched_text=self.matched_text,
            replacement_text=self.replacement_text,
            match_count=self.match_count,
            instruction_type=self.instruction_type,
        )

    def __eq__(self, other):
        if not isinstance(other, VerifiedCorrectionResponseInstruction):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "VerifiedCorrectionResponseInstruction(%r)" % (self.to_dict(),)

    @classmethod
    def from_dict(cls, data):
        """Reconstruct a `VerifiedCorrectionResponseInstruction` from a
        plain dict shaped like `to_dict()`'s output - the SAME
        `__init__`/keyword-argument reconstruction convention
        `VerifiedCorrectionResponseInput.from_dict()` already uses.

        `data` must be a dict; anything else raises `TypeError`. `data`
        is never mutated. Required fields are taken exactly as given -
        a `data` missing one of them raises `TypeError` from
        `__init__` itself (Python's own "missing required argument"
        behavior); a `data` carrying an invalid value for one of them
        raises `ValueError` from `__init__` exactly as direct
        construction does.
        """
        if not isinstance(data, dict):
            raise TypeError("data must be a dict")
        return cls(**data)


def build_verified_correction_response_instruction(
        source_text, corrected_text, matched_text, replacement_text,
        match_count, instruction_type=INSTRUCTION_TYPE_USE_CORRECTED_TEXT):
    """Build a `VerifiedCorrectionResponseInstruction` from six
    already-known values - the SAME "one small, focused builder
    function next to the structure it builds" convention this package
    already uses (e.g. `build_verified_correction_response_input()`).
    Adds no logic beyond `VerifiedCorrectionResponseInstruction.
    __init__` itself: invalid data raises exactly the same
    `ValueError` construction already raises.
    """
    return VerifiedCorrectionResponseInstruction(
        source_text=source_text,
        corrected_text=corrected_text,
        matched_text=matched_text,
        replacement_text=replacement_text,
        match_count=match_count,
        instruction_type=instruction_type,
    )
