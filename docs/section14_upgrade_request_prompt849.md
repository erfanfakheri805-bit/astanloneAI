# Prompt 849 - Self-Upgrade Request Contract

First step of Section 14 (Self-Upgrade Engine).
Module: `upgrade/upgrade_request.py` (new package `upgrade/`, empty `__init__.py`) - a strict, JSON-safe data contract describing WHAT upgrade is requested. It plans nothing, inspects/generates no source code, modifies no project file, executes nothing and is not connected to Core, Memory, AEL, the Capability System or any external service. Pure Python with no imports. Nothing is inferred, coerced, trimmed or repaired.

## Normalized request (exactly seven keys)
`version` (exactly the string `"1"`), `request_id` (text <= 64), `goal` (text <= 500), `scope` (list, <= 16 items, each text <= 200), `constraints` (same), `requested_by` (text <= 64), `execution_allowed` (exactly the bool `False`).
"Text" follows the Prompt 841 text convention: exact `str`, non-empty, no outer whitespace, no control characters, bounded. Lists are exact `list`s; an empty list is a stated value (not a guess); items are not de-duplicated or reordered.

## API
- `build_upgrade_request(request=None)` -> `{valid, errors, upgrade_request, execution_allowed, executed}`. `request` is an exact dict with the five required keys; `version` and `execution_allowed` are optional and, when supplied, must already be exactly `"1"` / `False` (`execution_allowed=True` is rejected, not ignored). Unknown keys are rejected; missing keys are errors; `None` is `missing_request`. `upgrade_request` is a fresh normalized copy when valid, else None.
- `validate_upgrade_request(upgrade_request)` -> `{valid, errors, execution_allowed, executed}`. Requires all seven keys and no others.

`errors`: `[{code, where}]`, at most 16, fixed order. Codes: `missing_request`, `request_not_dict`, `too_many_fields`, `unexpected_field`, `missing_field`, `invalid_version`, `invalid_request_id`, `invalid_goal`, `invalid_scope`, `invalid_constraints`, `invalid_requested_by`, `invalid_execution_allowed`, `too_many_items`, `invalid_item` (where `scope[i]` / `constraints[i]`), `validation_error`.
`execution_allowed` and `executed` are always False in every result.

Bounded work (oversized lists/dicts are rejected without scanning), read-only, deterministic, fresh, never raises. No existing module was changed; no other package imports `upgrade`.

Tests: `tests/test_upgrade_request_prompt849.py` (30 tests: valid, missing request/goal, request_id, scope, constraints, requested_by, execution_allowed, malformed input, bounds, safety, boundaries).
