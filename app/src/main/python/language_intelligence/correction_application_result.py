"""
Language Intelligence - Correction Application Result
========================================================================
Prompt 474. A small, structured outcome for a FUTURE correction-
application step over an EXISTING Prompt 473
`CorrectionApplicationRequest`. This module adds ONLY the result
model and its constants - no text replacement, no response-generation
integration, and no connection to Learning, Memory, Knowledge, Meaning
Resolution, Correction Understanding, Correction Lookup, Correction
Selection, `ResponseGenerationContext`, the Local Model Runtime,
backend selection, model inference, `AgentLoop`, or Self-Upgrade
happens here. Whatever later step actually applies a request is a
separate, explicitly scoped piece of work; this module only names the
shape of its eventual outcome, the SAME "add the result object before
the operation that produces it exists" posture
`correction_learning_handoff_result.py` (Prompt 458) already used for
`CorrectionLearningHandoffResult`.

Statuses
---------
    APPLIED       the correction was successfully applied.
    NOT_APPLIED   the correction was intentionally not applied (for
                   example, an application step decides the request is
                   not ready, or that applying it is not warranted) -
                   distinct from a failure: nothing went wrong, the
                   correction was simply not applied.
    FAILED        an application attempt was made but did not
                   succeed.

Fields (only these eleven; nothing else is carried)
----------------------------------------------------
    status           one of `ALL_STATUSES` (`APPLIED` / `NOT_APPLIED` /
                     `FAILED`) - required; `ValueError` for anything
                     else, the SAME "status not in ALL_STATUSES ->
                     raise" posture `CorrectionLearningHandoffResult`
                     already uses.
    applied          bool; always `status == STATUS_APPLIED`, never
                     set independently of `status` - the SAME
                     "derived, never independent" posture that
                     module's own `accepted` field already uses.
    original_text    the text the correction would replace, when
                     available; `None` otherwise. Carried through
                     unchanged - never derived, guessed, or
                     normalized here.
    corrected_text   the text the correction would produce, when
                     available; `None` otherwise. Carried through
                     unchanged.
    reason           an existing explanation for `NOT_APPLIED` or
                     `FAILED`, reused verbatim when one is already
                     available; `None` otherwise (typically `None` for
                     `APPLIED`). Never an invented explanation - the
                     SAME rule `CorrectionLearningHandoffResult.reason`
                     already follows.
    metadata         a small, optional, JSON-shaped dict of additional
                     detail about the outcome; `{}` when not supplied.
                     Deep-copied at construction time and again by
                     `to_dict()`, the SAME `copy.deepcopy()` convention
                     `CorrectionApplicationCandidate.
                     corrected_expression_or_meaning` (Prompt 470)
                     already uses for its own mutable, caller-shaped
                     field - mutating the dict passed in, or the dict
                     `to_dict()` returns, never reaches back into this
                     result.
    matched_text     Prompt 478. The exact original expression that
                     was matched (the SAME string an application step
                     already matched with EXACT, literal, case-
                     sensitive substring matching - never re-derived,
                     never fuzzy, never normalized). Populated for
                     `APPLIED`; `None` when not available, the SAME
                     "carried through, never guessed" rule
                     `original_text`/`corrected_text` already follow.
    replacement_text Prompt 478. The exact corrected expression that
                     was inserted in place of `matched_text`.
                     Populated for `APPLIED`; `None` when not
                     available.
    match_count      Prompt 478. The number of exact occurrences that
                     were replaced; an `int`, always `0` for
                     `NOT_APPLIED` and `FAILED` (nothing was
                     replaced), and always greater than zero for
                     `APPLIED` (at least one exact occurrence was
                     replaced). Carried through unchanged - never
                     derived, guessed, or re-counted here; `0` when
                     not supplied.
    text_before      Prompt 479. The exact target text that was
                     supplied to the correction-application operation
                     - the SAME value as `original_text`, exposed
                     under this name. Defaults to `original_text` when
                     not given explicitly; never re-derived from
                     anything else.
    text_after       Prompt 479. The target text after the attempted
                     correction: the resulting corrected text for
                     `APPLIED` (the SAME value as `corrected_text`),
                     or the unchanged supplied target for
                     `NOT_APPLIED` and `FAILED` (the SAME value as
                     `original_text`, so a `FAILED` result with no
                     safely-available target text is `None` here too
                     - never a falsely-implied successful correction).
                     Defaults from `status`/`original_text`/
                     `corrected_text` when not given explicitly; never
                     re-derived by re-running the correction.

Nothing performed here
-------------------------
This module performs no text replacement, no fuzzy matching, no
semantic similarity, no guessing, no automatic correction, and
introduces no new storage. It does not modify
`ResponseGenerationContext`, the Local Model Runtime, backend
selection, model inference, `AgentLoop`, or Self-Upgrade, and it does
not touch Learning, Memory, Knowledge, Meaning Resolution, Correction
Understanding, Correction Lookup, or Correction Selection. It is a
small, deterministic, read-only result shape only - nothing about how
or whether a correction gets applied is decided here.

Backward compatible
-----------------------
This is a new, additive module. No existing file, class, function, or
constant is modified, renamed, or removed.

Prompt 478 addendum - matched_text / replacement_text / match_count
------------------------------------------------------------------------
These three fields are additive, optional constructor keyword
arguments (each defaults to `None`/`0` so every existing caller and
every existing positional/keyword call site remains valid unchanged).
Nothing about `status`, `applied`, `original_text`, `corrected_text`,
`reason`, or `metadata` - their meaning, their defaults, or how they
are computed - changes. `to_dict()`, `__eq__()`, and `__repr__()` are
extended to also cover the three new fields (the same "the whole
`to_dict()` shape participates" convention this class already used for
its first six fields), so any existing caller comparing two results or
serializing one keeps working exactly as before, just with three more
keys present. No new matching, replacement, or correction-application
logic is added anywhere in this module - it still only holds a result
shape.

Prompt 479 addendum - text_before / text_after
---------------------------------------------------
These two fields are additive, optional constructor keyword arguments
that default to being DERIVED from the SAME values already passed to
this same constructor call - never re-derived by re-running any
matching or replacement logic, and never requiring any existing caller
to change:

    text_before   defaults to `original_text` when not given
                  explicitly.
    text_after    defaults to `corrected_text` when `status` is
                  `APPLIED`, else to `original_text` (unchanged target
                  text), when not given explicitly.

Because every existing caller of this constructor already passes
`original_text` and (for `APPLIED`) `corrected_text`, both new fields
are correctly populated everywhere without any existing call site
needing to change - the SAME "additive, backward compatible" posture
Prompt 478 already used for `matched_text` / `replacement_text` /
`match_count`. `to_dict()`, `__eq__()`, and `__repr__()` are extended
to also cover these two fields.
"""

import copy

STATUS_APPLIED = "APPLIED"
STATUS_NOT_APPLIED = "NOT_APPLIED"
STATUS_FAILED = "FAILED"
ALL_STATUSES = (STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED)


class CorrectionApplicationResult:
    """The minimum useful fields describing one correction-application
    attempt's outcome - nothing more. See the module docstring for the
    exact meaning of each field.

    Immutable (slots, no setters) and comparable by value; carries no
    behavior beyond `to_dict()`. Never applies anything itself - see
    the module docstring.
    """

    __slots__ = (
        "status", "applied", "original_text", "corrected_text",
        "reason", "metadata", "matched_text", "replacement_text",
        "match_count", "text_before", "text_after",
    )

    def __init__(self, status, original_text=None, corrected_text=None,
                 reason=None, metadata=None, matched_text=None,
                 replacement_text=None, match_count=0,
                 text_before=None, text_after=None):
        if status not in ALL_STATUSES:
            raise ValueError(
                "status must be one of %r, got %r" % (ALL_STATUSES, status)
            )
        self.status = status
        self.applied = status == STATUS_APPLIED
        self.original_text = original_text
        self.corrected_text = corrected_text
        self.reason = reason
        self.metadata = copy.deepcopy(metadata) if metadata else {}
        self.matched_text = matched_text
        self.replacement_text = replacement_text
        self.match_count = match_count if match_count else 0
        self.text_before = (
            text_before if text_before is not None else original_text
        )
        if text_after is not None:
            self.text_after = text_after
        elif self.applied:
            self.text_after = corrected_text
        else:
            self.text_after = original_text

    def to_dict(self):
        """This result as a plain, JSON-shaped dict - the same
        `to_dict()` convention this package's other result objects
        already follow (e.g. `CorrectionLearningHandoffResult`,
        `CorrectionApplicationCandidate`). `metadata` is deep-copied
        again here, so mutating the returned dict never reaches back
        into this result."""
        return {
            "status": self.status,
            "applied": self.applied,
            "original_text": self.original_text,
            "corrected_text": self.corrected_text,
            "reason": self.reason,
            "metadata": copy.deepcopy(self.metadata),
            "matched_text": self.matched_text,
            "replacement_text": self.replacement_text,
            "match_count": self.match_count,
            "text_before": self.text_before,
            "text_after": self.text_after,
        }

    def __eq__(self, other):
        if not isinstance(other, CorrectionApplicationResult):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "CorrectionApplicationResult(%r)" % (self.to_dict(),)
