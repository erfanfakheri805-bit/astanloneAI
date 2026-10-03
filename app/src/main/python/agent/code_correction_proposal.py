"""
Agent - Code Correction Proposal
====================================
Connects the existing `CodeErrorAnalysis`
(agent/code_error_analysis.py's `build_code_error_analysis`) to one
small, structured, inert correction *proposal* - never an applied
change, and never a second copy of anything this project already has
for "propose without applying":

    CodeErrorAnalysis -> build_code_correction_proposal()
        -> {target_file, error_type, reason, change_description,
            status, ready_to_apply, apply_capability}

Reuses, never duplicates:
  - `agent.code_error_analysis.build_code_error_analysis` (Prompt 340)
    is the sole source of truth this module reads from - `error_type`/
    `is_actionable`/`target_file`/`line_number`/`error_message` are all
    read directly off its already-computed output, never re-derived
    from a raw execution/evaluation result a second way. Because that
    module's own `is_actionable` is already `True` only for a `FAILED`
    or `TIMEOUT` execution whose exception was one of the recognized,
    named families (see its own docstring), checking `is_actionable`
    here already enforces requirement 4's "execution/evaluation status
    is FAILED or TIMEOUT" gate - this module never re-reads a raw
    `execute_generated_code` status a second, disagreeing way.
  - `execution.code_change_plan_capability.CAPABILITY_NAME` (the
    project's existing, already-working "plan - but never apply - one
    exact-fragment text change" capability) is imported, unchanged,
    and referenced under this proposal's own `apply_capability` field
    - naming the existing system a later, separate, explicitly-invoked
    step could use to actually plan a concrete fragment-level edit,
    once real `old_text`/`new_text` source fragments are available
    from somewhere else. This module never calls that capability
    itself: doing so needs a real `old_text` fragment to search for,
    and `CodeErrorAnalysis` carries no source text at all (only
    `stderr`, a `line_number`, and a message) - inventing one would
    violate requirement 7 ("do not invent source-code fragments that
    are not available"), so this module only ever *points at* the
    existing planning capability, never fabricates the input it needs.
  - `status`/`reason` - the same two field names, with the same
    "controlled vocabulary decided by nothing but already-known facts"
    meaning, `planning.adaptive_plan_proposal.PlanProposal`/
    `agent.code_change_evaluation.build_code_change_evaluation` already
    use for their own, unrelated proposals/evaluations - reused as
    field *names* for consistency, not as a shared implementation
    (this module's own two-way `PROPOSED`/`NOT_READY` vocabulary is
    deliberately smaller and answers a different, narrower question:
    "is enough deterministically known to describe - never apply - a
    correction", not "should the Plan's structure change"). Likewise
    `ready_to_apply` reuses the exact field name/meaning
    `code_change_plan_capability.py`'s own handler already returns -
    always `False` here, since this module, unlike that capability,
    never even validates a concrete fragment against the file; a
    caller that wants a real, validated, fragment-level plan still has
    to go through `code_change_plan` itself, separately, with real
    source text.

Deterministic, per-`error_type` templates only (requirement 3, small
step; requirement 7, never invented source): `_CHANGE_DESCRIPTION_
TEMPLATES` below is a fixed, one-entry-per-recognized-`error_type`
lookup - the exact same six `error_type`/`ERROR_TYPE_TIMEOUT` values
`code_error_analysis.py` already defines as actionable, nothing more,
nothing guessed. A `change_description` only ever names *what kind* of
correction is called for and *where* (`target_file`, and a line number
when `CodeErrorAnalysis` actually found one) - it never proposes
specific replacement code, since none is ever available to this
module.

`status` (requirement 5, 8) is exactly one of:
    `PROPOSED`   - `is_actionable` was `True` and `target_file` (the
                   one other fact this module cannot do without) is
                   present - a correction is deterministically
                   describable, though never applied.
    `NOT_READY`  - anything else: `error_analysis` isn't even a real
                   `CodeErrorAnalysis` dict, `is_actionable` is
                   `False` (a successful execution, a rejected/never-
                   run one, or an error this project doesn't yet
                   recognize closely enough to act on), or
                   `target_file` is missing - never guessed at, always
                   reported honestly as "not enough is known" rather
                   than invented (requirement 8).

Describes, never applies, a correction (requirement 6, 12): nothing in
this module ever opens, reads the contents of, or writes to
`target_file` (or any other file) - `change_description`/`reason` are
built purely from the plain strings `CodeErrorAnalysis` already
carries. `ready_to_apply` is always `False`; this module has no
"apply" method, calls no capability that would apply anything, and
never mutates a Goal/Plan/PlanStep. Never re-executes the generated
code (requirement 13) - it reads only the already-produced
`CodeErrorAnalysis`, never `execute_generated_code` itself.

Never raises: any input that isn't a real `CodeErrorAnalysis` dict is
reported as `status=NOT_READY`, `change_description=None`, with an
explanatory `reason` - the same "always return a structured, honest
verdict" convention `build_code_error_analysis`/
`build_generated_code_execution_evaluation` already follow.

Prompt 347 - learned patterns as optional, advisory-only context:
`learned_patterns`, when passed, is expected to be whatever
`agent.code_correction_pattern_retrieval.
retrieve_successful_correction_patterns` (Prompt 346, wrapped by
`AgentLoop.retrieve_successful_correction_patterns`) already returned
for this same error's own `error_type` - never re-retrieved or
re-derived here (requirement 1). It is carried through, unmodified,
as the `learned_patterns` field of the returned dict (requirement 9's
"preserve ... learned patterns"). It never changes `status`/`ready`
below in any way (requirement 4, "must still validate the current
error independently"; requirement 7, "never treat a learned pattern
as proof the current correction is valid"). Omitted, `None`, or
anything that isn't a plain `list` is normalized to `[]` (requirement
8's "no learned pattern exists" case behaves exactly like the
pre-Prompt-347 call with no context at all).

Prompt 348 - a *relevant, successful* learned pattern may be
referenced as supporting context, never as proof:
A pattern in `learned_patterns` is "relevant" (requirement 3) only
when its own `pattern`/`outcome` fields (read via `_pattern_field`
below, off either a `LearningRecord` or the `to_dict()`-shaped dict
`AgentLoop.retrieve_successful_correction_patterns` returns - never a
second matching algorithm) equal this proposal's own already-computed
`error_type` and `code_correction_learning.OUTCOME_SUCCESS` - i.e. the
exact same "successful correction for this error_type" fact Prompt
346 already established, simply re-checked here (defensively, since
this function never assumes a caller only ever hands it patterns for
the current error) rather than blindly trusted (requirement 5). Only
the *first* such match is used, and only ever as one extra, plainly-
hedged sentence appended to `change_description` (requirement 3) -
`reason`/`status`/`target_file`/`error_type` are completely
unaffected, and `change_description` is still built first, exactly as
before, from `error_analysis` alone (requirement 4). This never
happens at all when `status` is `NOT_READY` (requirement 9 - nothing
is available to make a proposal more specific about in the first
place) or when `learned_patterns` holds nothing relevant/successful
for this `error_type` (requirement 8 - normal proposal behavior,
unchanged from Prompt 347).

`learned_pattern_used` (requirement 6) is the one new field this
prompt adds: `True` only when a relevant, successful pattern was
actually found and referenced as above (requirement 7); `False` in
every other case, including every `NOT_READY` result. It is a report
of what happened, never a claim that the pattern *is* correct
(requirement 5) - nothing here copies a prior correction's own text
into this proposal, calls `code_change_plan`, or applies anything
(requirements 10, 13); this module still has no code path that could.
"""

from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_CAPABILITY_NAME,
)
from .code_error_analysis import (
    ERROR_TYPE_SYNTAX,
    ERROR_TYPE_NAME,
    ERROR_TYPE_TYPE,
    ERROR_TYPE_IMPORT,
    ERROR_TYPE_RUNTIME,
    ERROR_TYPE_TIMEOUT,
)
from .code_correction_learning import OUTCOME_SUCCESS

STATUS_PROPOSED = "PROPOSED"
STATUS_NOT_READY = "NOT_READY"

ALL_CODE_CORRECTION_PROPOSAL_STATUSES = (STATUS_PROPOSED, STATUS_NOT_READY)

# Fixed, deterministic, one-per-recognized-error_type template
# (requirements 3, 7): describes only the *kind* and *location* of
# correction called for - never specific replacement source, since
# CodeErrorAnalysis never carries any. `{location}` is always either
# "" or " at line N" - substituted below, never invented beyond what
# CodeErrorAnalysis's own line_number already reports.
_CHANGE_DESCRIPTION_TEMPLATES = {
    ERROR_TYPE_SYNTAX: (
        "Fix the syntax error in {target_file}{location} so the file "
        "parses as valid Python."
    ),
    ERROR_TYPE_NAME: (
        "Define or correctly reference the missing name reported in "
        "{target_file}{location}."
    ),
    ERROR_TYPE_TYPE: (
        "Correct the type mismatch reported in {target_file}{location}."
    ),
    ERROR_TYPE_IMPORT: (
        "Fix the missing or incorrect import reported in "
        "{target_file}{location}."
    ),
    ERROR_TYPE_RUNTIME: (
        "Investigate and fix the runtime error reported in "
        "{target_file}{location}."
    ),
    ERROR_TYPE_TIMEOUT: (
        "Review {target_file} for a possible infinite loop or excessive "
        "runtime and bound its execution."
    ),
}


def _not_ready_reason(is_dict, is_actionable, target_file):
    """One fixed, honest explanation per way a proposal can't be made
    - never a guess at what might be wrong, only a report of which
    already-known precondition wasn't met (requirement 8)."""
    if not is_dict:
        return "No error analysis was available; a correction cannot be safely proposed."
    if not is_actionable:
        return "No actionable error was identified; a correction cannot be safely proposed."
    if not target_file:
        return (
            "The failing file could not be identified; a correction cannot be "
            "safely proposed without knowing which file to change."
        )
    return "The detected error is not one this module can safely describe a correction for."


def _pattern_field(pattern, name):
    """Read `name` off one `learned_patterns` entry, which may be a
    `LearningRecord` (the shape `agent.code_correction_pattern_
    retrieval.retrieve_successful_correction_patterns` itself returns)
    or the `to_dict()`-shaped dict `AgentLoop.retrieve_successful_
    correction_patterns` returns instead - the exact two shapes
    Prompt 347 already accepts into `learned_patterns`, nothing new.
    Anything else - or a missing attribute/key - yields `None`, never
    raises (same "safe on a miss" convention this module already
    follows throughout)."""
    if isinstance(pattern, dict):
        return pattern.get(name)
    return getattr(pattern, name, None)


def _first_relevant_successful_pattern(learned_patterns, error_type):
    """The first entry in `learned_patterns` that is actually relevant
    to `error_type` - its own `pattern` field equals `error_type` -
    *and* was itself recorded as `OUTCOME_SUCCESS` (requirement 3,
    "relevant successful pattern"; requirement 5, re-checked here
    rather than assumed just because a caller put it in the list).
    `None` when `error_type` is falsy or nothing in the list matches
    both conditions - the exact "no relevant pattern exists, normal
    proposal behavior" case requirement 8 asks for."""
    if not error_type:
        return None
    for pattern in learned_patterns:
        if (
            _pattern_field(pattern, "pattern") == error_type
            and _pattern_field(pattern, "outcome") == OUTCOME_SUCCESS
        ):
            return pattern
    return None


# One fixed, deterministic, plainly-hedged sentence (requirement 5:
# never presented as a guarantee) appended to change_description when
# - and only when - a relevant, successful pattern was actually found
# (requirement 3, 7). Never includes anything read out of the pattern
# itself - no prior correction text exists to copy in the first place
# (see learning.learning_record.LearningRecord's own fields).
_LEARNED_PATTERN_SUFFIX = (
    " A previously successful correction pattern for this error type is "
    "available as supporting context, though it is not a guarantee this "
    "correction is correct."
)


def build_code_correction_proposal(error_analysis, learned_patterns=None):
    """Build the small, structured, inert correction proposal
    `AgentLoop.propose_code_correction` (agent/agent_loop.py) exposes,
    on top of - and without duplicating - the existing `CodeErrorAnalysis`
    `error_analysis` already is.

    `learned_patterns` (Prompt 347, optional): previously-successful
    correction patterns for this same `error_analysis["error_type"]`,
    typically `AgentLoop.retrieve_successful_correction_patterns(
    error_analysis["error_type"])` (Prompt 346) - carried through into
    the returned dict's own `learned_patterns` field. It never changes
    `status`/`ready` below in any way (requirement 4, "must still
    validate the current error independently"; requirement 7, "never
    treat a learned pattern as proof the current correction is
    valid"). Omitted, `None`, or anything that isn't a plain `list` is
    normalized to `[]` (requirement 8).

    Prompt 348: when `status` is `PROPOSED` *and* `learned_patterns`
    contains an entry that is both relevant to this `error_type` and
    recorded as successful (see `_first_relevant_successful_pattern`),
    that single pattern is referenced as supporting context - one
    fixed, hedged sentence (`_LEARNED_PATTERN_SUFFIX`) appended to
    `change_description`, and `learned_pattern_used` set to `True`.
    Otherwise `change_description` is exactly what it always was and
    `learned_pattern_used` is `False` - including, always, whenever
    `status` is `NOT_READY` (requirement 9).

    Always returns:
        {
            "target_file": <error_analysis["target_file"], or None>,
            "error_type": <error_analysis["error_type"], or None>,
            "reason": <str - see module docstring>,
            "change_description": <str describing the kind/location of
                                   correction called for, optionally
                                   with the learned-pattern sentence
                                   appended, or None when status is
                                   NOT_READY>,
            "status": <"PROPOSED" or "NOT_READY" - see module
                       docstring>,
            "ready_to_apply": False,  # always - this module never
                                       # applies anything (requirement 10)
            "apply_capability": <execution.code_change_plan_capability.
                                 CAPABILITY_NAME when status is
                                 PROPOSED, reused unchanged, never
                                 called; otherwise None>,
            "learned_patterns": <the normalized `learned_patterns`
                                 list above, carried through - advisory
                                 only, see module docstring>,
            "learned_pattern_used": <True only when a relevant,
                                     successful pattern was actually
                                     referenced above; False otherwise
                                     - see module docstring>,
        }

    Generates a proposal (requirement 4) only when `error_analysis`
    reports `is_actionable=True` *and* a `target_file` is present -
    both already-computed facts, read directly, never re-derived.
    Every other case is `NOT_READY` (requirement 9), with `reason`
    explaining exactly why, never a guessed-at correction. This holds
    regardless of what `learned_patterns` contains - a matching,
    successful learned pattern is never treated as proof the current
    correction is valid (requirement 5), and its presence or absence
    never flips `NOT_READY` to `PROPOSED` or back.

    Purely a read-only, inert proposal step: never reads or writes
    `target_file` (or any other file) (requirement 11), never calls
    `code_change_plan` or any other capability, never re-executes the
    generated code (requirement 12), and never applies anything itself
    - including never auto-copying or auto-applying anything out of
    `learned_patterns` (requirement 10). Never raises - a malformed
    `error_analysis` (not a dict, or missing the fields
    `CodeErrorAnalysis` always carries) is reported as
    `status=NOT_READY` with an explanatory `reason`, exactly like
    every other precondition this function checks."""
    is_dict = isinstance(error_analysis, dict)
    target_file = error_analysis.get("target_file") if is_dict else None
    error_type = error_analysis.get("error_type") if is_dict else None
    error_message = error_analysis.get("error_message") if is_dict else None
    line_number = error_analysis.get("line_number") if is_dict else None
    is_actionable = bool(error_analysis.get("is_actionable")) if is_dict else False

    # Advisory-only context (requirements 5, 7): normalized here, never
    # consulted by the `ready`/status logic below.
    normalized_learned_patterns = list(learned_patterns) if isinstance(learned_patterns, list) else []

    ready = is_dict and is_actionable and bool(target_file) and error_type in _CHANGE_DESCRIPTION_TEMPLATES

    if not ready:
        return {
            "target_file": target_file,
            "error_type": error_type,
            "reason": _not_ready_reason(is_dict, is_actionable, target_file),
            "change_description": None,
            "status": STATUS_NOT_READY,
            "ready_to_apply": False,
            "apply_capability": None,
            "learned_patterns": normalized_learned_patterns,
            "learned_pattern_used": False,
        }

    location = f" at line {line_number}" if isinstance(line_number, int) else ""
    change_description = _CHANGE_DESCRIPTION_TEMPLATES[error_type].format(
        target_file=target_file, location=location,
    )
    reason = (
        f"{error_type} detected in {target_file}{location}: {error_message}"
        if error_message
        else f"{error_type} detected in {target_file}{location}."
    )

    relevant_pattern = _first_relevant_successful_pattern(normalized_learned_patterns, error_type)
    learned_pattern_used = relevant_pattern is not None
    if learned_pattern_used:
        change_description = change_description + _LEARNED_PATTERN_SUFFIX

    return {
        "target_file": target_file,
        "error_type": error_type,
        "reason": reason,
        "change_description": change_description,
        "status": STATUS_PROPOSED,
        "ready_to_apply": False,
        "apply_capability": CODE_CHANGE_PLAN_CAPABILITY_NAME,
        "learned_patterns": normalized_learned_patterns,
        "learned_pattern_used": learned_pattern_used,
    }
