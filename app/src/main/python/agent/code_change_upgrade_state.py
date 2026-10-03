"""
Agent - Code Change Upgrade State
======================================
Prompt 356: a small, deterministic state model that tracks one
CODE_CHANGE self-upgrade at a time on top of the existing Unified Code
Upgrade Result (agent/code_change_upgrade_result.py, Prompt 354,
unchanged) - never a second AgentLoop and never a second state system:

    "start" (a caller's own decision to begin a CODE_CHANGE upgrade)
        -> can_start_upgrade(current_state)
        -> True/False

    upgrade_result (agent.code_change_upgrade_result.
                     build_code_change_upgrade_result, Prompt 354,
                     unchanged)
        -> next_upgrade_state_from_result()
        -> next state

Reuses, never duplicates:
  - `agent.code_change_upgrade_result.FINAL_STATUS_SUCCESS`/
    `FINAL_STATUS_FAILED`/`FINAL_STATUS_ROLLED_BACK`/
    `FINAL_STATUS_REJECTED` - Prompt 354's own, already-computed,
    already-deterministic four-way verdict for one finished CODE_CHANGE
    self-upgrade flow - are imported, unchanged, as the only input this
    module's own state transition reads. This module never re-derives
    `final_status` itself, never re-reads `readiness_result`/
    `snapshot_result`/`rollback_result`, and never runs any part of the
    existing CODE_CHANGE/audit/validation/testing/version/rollback
    pipeline (Prompts 349-354) a second time.
  - `AgentLoop`'s own existing state/context (agent/agent_loop.py) is
    where this module's one small piece of state - a single current
    state string - is meant to live (as `AgentLoop._upgrade_state`,
    exposed via `AgentLoop.get_upgrade_state()`/`AgentLoop.
    start_code_change_upgrade()`) - this module itself defines no
    class, no store, and no second AgentLoop of its own; it only
    supplies the fixed vocabulary and the two small, pure functions
    `AgentLoop` calls to read/advance that one attribute (requirement
    8: "do not create a second AgentLoop or state system").

`ALL_CODE_CHANGE_UPGRADE_STATES` (requirement 2) is exactly:
    `IDLE`         - no CODE_CHANGE upgrade has started yet, or the
                     most recent one already reached a terminal state
                     and a new one has not yet been started.
    `IN_PROGRESS`  - a CODE_CHANGE upgrade has been started
                     (`can_start_upgrade` returned `True` for it) and
                     has not yet received its Unified Code Upgrade
                     Result.
    `COMPLETED`    - the most recently received Unified Code Upgrade
                     Result's `final_status` was `SUCCESS`.
    `FAILED`       - the most recently received Unified Code Upgrade
                     Result's `final_status` was `FAILED`.
    `ROLLED_BACK`  - the most recently received Unified Code Upgrade
                     Result's `final_status` was `ROLLED_BACK`.
    `REJECTED`     - the most recently received Unified Code Upgrade
                     Result's `final_status` was `REJECTED`.

`can_start_upgrade(current_state)` (requirement 5) is the one, fixed
gate a caller (`AgentLoop.start_code_change_upgrade`) checks before
moving to `IN_PROGRESS`: it is `False` only when `current_state` is
already `IN_PROGRESS` - a new upgrade may start from `IDLE` or from any
of the four terminal states (`COMPLETED`/`FAILED`/`ROLLED_BACK`/
`REJECTED`) exactly the same way, never treating a past failure/
rejection/rollback as a reason to block a *new, separately, explicitly
started* upgrade (that would be requirement 7's "do not automatically
retry" turned inside-out into "never let the operator retry either",
which this module deliberately does not do) - it only ever blocks a
second upgrade from starting while one is still running.

`next_upgrade_state_from_result(upgrade_result, current_state)`
(requirement 3) is the one, fixed, deterministic transition a caller
(`AgentLoop.build_code_change_upgrade_result`) applies whenever a
Unified Code Upgrade Result is received: it reads nothing but that
result's own `final_status` field and maps it, via the fixed table
above, onto exactly one of `COMPLETED`/`FAILED`/`ROLLED_BACK`/
`REJECTED` - the same terminal state regardless of what `current_state`
was beforehand (a result is always "the" answer for whichever upgrade
just finished). A malformed `upgrade_result` (not a dict, or a
`final_status` that isn't one of Prompt 354's own four values) leaves
`current_state` completely unchanged rather than guessing at a new one
- the one deliberately conservative exception to "always deterministic
from the result alone", since an unrecognizable result carries no
actual verdict to transition on.

Never starts, retries, or reverses anything of its own (requirements
6, 7): this module contains no call to any correction, validation,
sandbox, version, rollback, or upgrade-result method - it only reads
one already-computed field and looks it up in one fixed table. A
`FAILED`/`REJECTED`/`ROLLED_BACK` state is only ever *reported* here;
reaching it never starts a new upgrade, never re-applies a change, and
never re-runs a test - the exact same "report a terminal state, never
act on it" guarantee `agent.code_change_upgrade_result` itself already
gives at the layer below.

Never raises: both functions accept whatever they are given, and use
only their one fixed, safe fallback each (`can_start_upgrade` treats
anything other than `IN_PROGRESS` as startable; `next_upgrade_state_
from_result` leaves `current_state` unchanged on unrecognizable input)
- same "never raises, report what could be determined" convention
every other module in this project's CODE_CHANGE pipeline (Prompts
349-354) already follows.
"""

from .code_change_upgrade_result import (
    FINAL_STATUS_SUCCESS,
    FINAL_STATUS_FAILED,
    FINAL_STATUS_ROLLED_BACK,
    FINAL_STATUS_REJECTED,
)

STATE_IDLE = "IDLE"
STATE_IN_PROGRESS = "IN_PROGRESS"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"
STATE_ROLLED_BACK = "ROLLED_BACK"
STATE_REJECTED = "REJECTED"

ALL_CODE_CHANGE_UPGRADE_STATES = (
    STATE_IDLE,
    STATE_IN_PROGRESS,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_ROLLED_BACK,
    STATE_REJECTED,
)

# Requirement 3: the one, fixed final_status -> terminal-state table -
# reuses agent.code_change_upgrade_result's own four FINAL_STATUS_*
# constants unchanged as the only keys, never a fifth, guessed-at one.
_FINAL_STATUS_TO_UPGRADE_STATE = {
    FINAL_STATUS_SUCCESS: STATE_COMPLETED,
    FINAL_STATUS_FAILED: STATE_FAILED,
    FINAL_STATUS_ROLLED_BACK: STATE_ROLLED_BACK,
    FINAL_STATUS_REJECTED: STATE_REJECTED,
}


def can_start_upgrade(current_state):
    """Requirement 5: `True` unless `current_state` is already
    `IN_PROGRESS` - a new CODE_CHANGE upgrade may start from `IDLE` or
    from any already-terminal state
    (`COMPLETED`/`FAILED`/`ROLLED_BACK`/`REJECTED`) exactly the same
    way. Never raises - any value other than the literal
    `STATE_IN_PROGRESS` is treated as startable, never guessed at
    further."""
    return current_state != STATE_IN_PROGRESS


def next_upgrade_state_from_result(upgrade_result, current_state=STATE_IDLE):
    """Requirement 3: compute the next CODE_CHANGE upgrade state from
    an already-built Unified Code Upgrade Result (`agent.code_change_
    upgrade_result.build_code_change_upgrade_result`, Prompt 354,
    unchanged) - reading nothing from it but its own `final_status`
    field, and never re-deriving that field itself.

    `upgrade_result` is expected to be exactly what `build_code_change_
    upgrade_result` already returns - only `upgrade_result
    ["final_status"]` is read.

    `current_state` is the state to fall back to when `upgrade_result`
    is malformed or carries an unrecognized `final_status` - defaults
    to `STATE_IDLE` for a caller with no prior state of its own, but a
    caller with an existing state (typically `AgentLoop._upgrade_state`)
    should always pass it explicitly so a malformed result never
    silently resets an in-progress or already-terminal state.

    Always returns one of `ALL_CODE_CHANGE_UPGRADE_STATES`:
    `STATE_COMPLETED` for `FINAL_STATUS_SUCCESS`, `STATE_FAILED` for
    `FINAL_STATUS_FAILED`, `STATE_ROLLED_BACK` for
    `FINAL_STATUS_ROLLED_BACK`, `STATE_REJECTED` for
    `FINAL_STATUS_REJECTED` - or `current_state`, unchanged, for
    anything else. Never raises."""
    final_status = upgrade_result.get("final_status") if isinstance(upgrade_result, dict) else None
    return _FINAL_STATUS_TO_UPGRADE_STATE.get(final_status, current_state)
