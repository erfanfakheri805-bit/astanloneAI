# Prompt 898 - Section 17: Approval Authority Source Contract

Fifth layer of Section 17 (Controlled Autonomy). New module: `autonomy/approval_authority_source.py` (`build_approval_authority_source`, `validate_approval_authority_source`). Deterministic, read-only, side-effect free. No historical production module (Section 16, Prompts 894-897) and no historical test was changed.

## Purpose

A future controlled-implementation flow will need an approval from some trusted source. Prompt 898 defines only a **descriptive** contract for WHAT KIND of authority could provide such an approval. It describes an authority that is capable of providing approval; it never provides approval. There is no `approved` status, no approval field, no authorization, no implementation permission, no execution permission, no code generation, no self-modification, no persistence, no filesystem mutation, no subprocess, no network, no external AI/API and no automatic behavior.

The module is connected to no user authentication, Android permission, account, UI, storage, network service or external authority.

## Descriptor (exactly nine keys)

| Key | Value |
|---|---|
| `version` | integer `1` |
| `authority_id` | snake_case label (`a-z`, `0-9`, `_`, starts with a letter, 1-64 chars) |
| `authority_type` | one of `user`, `system_policy`, `trusted_internal_controller` |
| `scope` | snake_case label of the same shape; no wildcard such as `all` / `any` / `global` |
| `purpose` | snake_case label of the same shape |
| `trusted` | `bool`: trusted by policy (descriptive only) |
| `approval_capable` | `bool`: conceptually capable of issuing approval (descriptive only) |
| `implementation_allowed` | `bool`, MUST be `False` |
| `execution_allowed` | `bool`, MUST be `False` |

`trusted` and `approval_capable` are independent descriptive flags; neither confers any permission. Values are primitives only. Every call returns a fresh dict, nothing supplied is modified, and results do not depend on time, randomness or environment.

Labels that look executable or dynamic are rejected: callables, objects, bytes and numbers by type; strings containing URLs, commands, code, keys or credentials by character set and by forbidden segments (`http`, `url`, `endpoint`, `api`, `key`, `secret`, `token`, `password`, `credential`, `callback`, `lambda`, `exec`, `eval`, `import`, `subprocess`, `shell`, `command`, `script`, `approved`, `granted`, `authorized`, `allowed`, ...).

## Statuses (the complete vocabulary)

| Status | Meaning |
|---|---|
| `valid` | descriptor is well-formed (still only a description; grants nothing) |
| `invalid_authority` | not a dict, missing or unexpected key, non-str key, wrong version |
| `invalid_authority_id` | empty, malformed, too long, non-str or executable-looking id |
| `unsupported_authority_type` | not one of the three supported types |
| `invalid_scope` | malformed, wildcard, non-str or executable-looking scope |
| `invalid_purpose` | malformed, non-str or executable-looking purpose |
| `invalid_flags` | any of the four flags is not a real `bool` |
| `forbidden_permission` | `implementation_allowed` or `execution_allowed` is `True` |
| `unsupported_status` | an approval / status concept (`approved`, `granted`, `status`, `approval_status`, ...) used as an authority type or as an extra field |
| `validation_error` | unexpected internal failure |

Checks run in a fixed order and the first failing group decides: shape, version, `authority_id`, `authority_type`, `scope`, `purpose`, flag types, forbidden permissions.

## Result shapes

`validate_approval_authority_source(descriptor)` returns `{"status", "valid", "errors", "execution_allowed", "executed"}`; `valid` is `True` only for `valid`, `errors` is a list of `{"code", "where"}` (at most `MAX_ERRORS`), `execution_allowed` and `executed` are always `False`.

`build_approval_authority_source(authority_id, authority_type, scope, purpose, trusted, approval_capable, implementation_allowed=False, execution_allowed=False)` returns `{"status", "descriptor", "execution_allowed", "executed"}`. `descriptor` is the fresh valid descriptor only for `valid` and is `None` otherwise, so a rejected request never yields a descriptor. The two permission parameters exist only so an attempt to set them to `True` is visibly rejected.

## Safety invariants

`implementation_allowed` and `execution_allowed` are always `False`. No filesystem I/O, network, API/model client, subprocess, `exec`/`eval`/`compile`, Memory/AEL/registry mutation, persistence, project modification, code or patch generation, approval, authorization, implementation, execution or self-modification. The module imports only `re` and `MAX_ERRORS`.
