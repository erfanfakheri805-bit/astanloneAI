# Prompt 857 - Upgrade Sandbox Workspace

Eighth step of Section 14 (Self-Upgrade Engine), after the request (849), project state (850), plan (851), change proposal (852), policy gate (854), change set (855) and transaction boundary (856).
Module: `upgrade/upgrade_sandbox.py` - a small, deterministic, purely IN-MEMORY virtual workspace. It never touches the real project: no filesystem scanning/read/write, subprocess, code or patch execution, project-code import, Core/Memory/AEL, API or network. A change set carries no source/patch content, so applying one records deterministic sandbox metadata only; no source or implementation is invented; no rollback or execution exists.

## Workspace (exactly five keys, fixed order)
`version` (`"1"`), `project_state` (fresh normalized Prompt 850 state: declared files with path/kind/status and declared capabilities), `applied` (<= 16 records `{proposal_id, changes}`, one per applied change set, changes unchanged and in order), `execution_allowed` (False), `executed` (False).

## API
- `build_sandbox_workspace(project_state)` -> `{valid, errors, workspace, execution_allowed, executed}`. Only a state passing `validate_project_state` (850, reused); `applied` starts empty. Error: `invalid_project_state`.
- `validate_sandbox_workspace(workspace)` -> `{valid, errors, execution_allowed, executed}`. Exact keys/types, version, state via `validate_project_state`, unique proposal ids, the 855 change rules (reused checkers), every change targeting a declared file (`modify_file`) or capability (`update_capability`), flags False.
- `apply_change_set_to_sandbox(workspace, change_set)` -> `{status, applied, changes, workspace, errors, execution_allowed, executed}`. Only a valid workspace and a change set passing `validate_change_set` (855, reused). Rejects unknown targets (`unknown_target`), a repeated (action, target) pair (`duplicate_change`), an already applied proposal id (`change_set_already_applied`) and a full workspace (`too_many_applied`); all-or-nothing. On success `status` `applied`, `changes` the recorded changes and a NEW workspace with one more record; on failure `status` `rejected`, `applied` False, `changes` [], `workspace` None. Inputs are never modified.

`errors` is `[{code, where}]`, at most 16, fixed order. `execution_allowed` and `executed` are always False in every result. Bounded, read-only, deterministic, fresh, never raises. No existing module was changed; nothing outside `upgrade/` imports the sandbox.

Tests: `tests/test_upgrade_sandbox_prompt857.py` (29 tests: build, fresh copies, apply, metadata-only, input immutability, sequential apply, unknown targets, all-or-nothing, invalid change set / workspace, duplicates, double apply, identity mismatch, bounds, malformed workspace, imports/no-I/O).
