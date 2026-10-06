# Prompt 850 - Upgrade Project State

Second step of Section 14 (Self-Upgrade Engine), after the Prompt 849 request contract.
Module: `upgrade/project_state.py` - a small, JSON-safe snapshot of the project state a future self-upgrade planner may need, built ONLY from structured metadata supplied by the caller. It reads, writes, scans and discovers no file, runs no test, changes no capability, generates no patch or code, performs no upgrade and is not connected to Core, Memory, AEL, the Capability System or any external service. Nothing is inferred, coerced, trimmed or repaired.

## Normalized project state (exactly eight keys)
`version` (exactly `"1"`), `project_id` (text <= 64), `revision` (text <= 64), `files` (list, <= 256 descriptors), `capabilities` (list, <= 64 items, each text <= 64), `tests` (list, <= 128 items, each text <= 200), `constraints` (list, <= 16 items, each text <= 200), `execution_allowed` (exactly the bool `False`).
Each file descriptor is an exact dict with exactly `path` (<= 200), `kind` (<= 64), `status` (<= 64) - all three required, no other keys. A path is an opaque caller-supplied label; it is never opened or resolved.
"Text" is the Prompt 849 / 841 convention, reused from `upgrade_request` (`_is_text`, `_add`, `_where` and error constants are imported, not duplicated): exact `str`, non-empty, no outer whitespace, no control characters, bounded. Containers must be the exact built-in `dict` / `list`; subclasses are rejected. Empty lists are stated values. Lists are not de-duplicated, sorted or reordered. The normalized object carries no `executed` key.

## API
- `build_project_state(source=None)` -> `{valid, errors, project_state, execution_allowed, executed}`. `source` is an exact dict with the six required keys; `version` and `execution_allowed` are optional and, when supplied, must already be `"1"` / `False` (`True` is rejected, not ignored). `project_state` is a fresh normalized copy (lists and descriptors copied) when valid, else None.
- `validate_project_state(project_state)` -> `{valid, errors, execution_allowed, executed}`. Requires all eight keys and no others.

`errors`: `[{code, where}]`, at most 16, fixed order. Codes: `missing_source` / `missing_state`, `source_not_dict` / `state_not_dict`, `too_many_fields`, `unexpected_field`, `missing_field`, `invalid_version`, `invalid_project_id`, `invalid_revision`, `invalid_files`, `invalid_capabilities`, `invalid_tests`, `invalid_constraints`, `invalid_execution_allowed`, `too_many_items`, `invalid_item` (where `capabilities[i]` etc.), `invalid_file` (`files[i]`), `too_many_file_fields`, `unexpected_file_field`, `missing_file_field`, `invalid_file_path` / `invalid_file_kind` / `invalid_file_status` (`files[i].path` etc.), `validation_error`.
`execution_allowed` and `executed` are always False in every result.

Bounded work (oversized containers are rejected without scanning their items), read-only, deterministic, fresh, never raises. No existing module was changed; no other package imports `project_state`.

Tests: `tests/test_project_state_prompt850.py` (24 tests: valid, missing fields, file descriptors, capabilities, tests, constraints, oversized collections, wrong types, execution attempts, malformed input, safety boundaries).
