# Prompt 899 - Section 17: Approval Authority Scope Boundary

Sixth layer of Section 17 (Controlled Autonomy). New module: `autonomy/approval_authority_scope.py` (`build_approval_authority_scope`, `validate_approval_authority_scope`, `validate_approval_authority_scope_context`). Deterministic, read-only, side-effect free. No existing production module was changed (Prompt 898 `approval_authority_source.py` is only imported) and no historical test was changed.

## Purpose

Prompt 898 describes WHAT KIND of authority could provide a future approval. Prompt 899 describes the **boundary** of what such an authority source could one day be asked to approve: exactly one authority, one capability and one operation. The scope is a boundary, not a grant. It never approves anything: there is no `approved` status, no approval or authorization field, no implementation permission, no execution permission, no code generation, no self-modification, no persistence, no filesystem mutation, no subprocess, no network, no external AI/API, no authentication or account integration and no automatic behavior.

## Scope descriptor (exactly ten keys)

| Key | Value |
|---|---|
| `version` | integer `1` |
| `scope_id` | snake_case label (Prompt 898 convention, 1-64 chars) |
| `authority_id` | label of the ONE authority; must equal the Prompt 898 descriptor's |
| `capability_name` | label of the ONE capability (no wildcard such as `all`) |
| `operation` | `create` or `improve`; `improve_or_conflict` is not supported |
| `scope` | label describing the boundary (no wildcard) |
| `purpose` | label |
| `approval_capable` | `bool`, copied from the trusted Prompt 898 descriptor |
| `implementation_allowed` | `bool`, MUST be `False` |
| `execution_allowed` | `bool`, MUST be `False` |

Every label is judged by the Prompt 898 validator itself, so the same rules apply: lower-case snake_case, no URL / command / code / key / credential / approval-word segment, no wildcard scope. Values are primitives only; every call returns fresh objects; nothing supplied is modified or shared with a result.

## Upstream context

The Prompt 898 authority descriptor is trusted only after the Prompt 898 validator says `valid`. A malformed authority, an authority with a permission flag set, or a forged dict subclass gives `invalid_authority` (an authority that only fails because of an approval/status concept gives `unsupported_status`). The scope must then equal the authority on `authority_id` and `approval_capable`, otherwise `context_mismatch`. `trusted` is not copied.

## Statuses (the complete vocabulary)

| Status | Meaning |
|---|---|
| `valid` | well-formed description (still only a boundary; grants nothing) |
| `invalid_authority` | authority descriptor invalid; scope not a dict, missing/unexpected key, wrong version, or invalid `authority_id` |
| `invalid_scope` | invalid `scope` or `purpose` label, or a non-boolean flag |
| `invalid_scope_id` | `scope_id` is not a valid label |
| `invalid_capability` | `capability_name` is not a valid label |
| `invalid_operation` | `operation` is not `create` / `improve` |
| `context_mismatch` | `authority_id` or `approval_capable` differs from the Prompt 898 descriptor |
| `forbidden_permission` | `implementation_allowed` or `execution_allowed` is `True` |
| `unsupported_status` | `improve_or_conflict`, or an approval/authorization concept (`approved`, `authorization`, `granted`, `status`, ...) used as an operation or as an extra field |
| `validation_error` | unexpected internal failure |

No status grants approval, authorization, permission or execution. Checks run in a fixed order and the first failing group decides: authority, shape, `authority_id`, `scope_id`, `capability_name`, `operation`, scope/purpose/flag types, forbidden permissions, context match.

## Result shapes

`validate_approval_authority_scope(scope)` is structural only (it does not know the authority); `validate_approval_authority_scope_context(authority, scope)` also checks the authority and the match. Both return `{"status", "valid", "errors", "execution_allowed", "executed"}`; `valid` is `True` only for `valid`; `execution_allowed` and `executed` are always `False`.

`build_approval_authority_scope(authority_descriptor, scope_id, capability_name, operation, scope, purpose, approval_capable=None, implementation_allowed=False, execution_allowed=False, authority_id=None)` copies `authority_id` and `approval_capable` from the authority when not supplied, validates with the context validation and returns `{"status", "scope_descriptor", "execution_allowed", "executed"}`. `scope_descriptor` is the fresh valid descriptor only for `valid` and is `None` otherwise, so a rejected request never yields a permission-bearing result. The optional `authority_id`, `approval_capable` and permission parameters exist only so a mismatch or an attempt to set a permission to `True` is visibly rejected.

## Safety invariants

`implementation_allowed` and `execution_allowed` are always `False`. No filesystem I/O, network, API/model client, subprocess, `exec`/`eval`/`compile`, Memory/AEL/registry mutation, persistence, project modification, code or patch generation, approval, authorization, implementation, execution or self-modification. The module imports only `MAX_ERRORS` and the Prompt 898 validator.
