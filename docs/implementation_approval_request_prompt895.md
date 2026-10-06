# Prompt 895 - Section 17: Implementation Approval Request

Second layer of Section 17 (Controlled Autonomy). New module: `autonomy/implementation_approval_request.py` (`build_implementation_approval_request`, `validate_implementation_approval_request`). It is deterministic, read-only and side-effect free. No Section 16 module, no Prompt 894 file and no historical manifest was changed.

## Why the approval request exists

Prompt 894 answers "may this request be considered?". Prompt 895 gives that answer a concrete, validated record that a future, separate step can read when it decides on approval. The record says one thing only: *an eligible implementation request may now be submitted for controlled approval*. It carries `approval_required=True` because approval is still missing.

## The four distinctions

- **Eligibility vs approval request** - eligibility (Prompt 894 `eligible`) is a verdict about the data. The approval request is a record built from that verdict plus the trusted request fields (purpose, inputs, outputs, constraints, existing capability). Only an `eligible` policy can produce one.
- **Approval request vs approval** - the request asks for a decision. Nothing here decides: there is no `approved` status or field, no approval engine, no user or AEL approval and no automatic approval. `ready_for_approval` is not `approved`.
- **Approval vs implementation permission** - even a future approval would be a separate fact from `implementation_allowed`. Prompt 895 keeps `implementation_allowed=False` and defines nothing that can set it.
- **Implementation permission vs execution** - permission to implement is not permission to run. `execution_allowed`, `implementation_started` and `executed` are always `False`.

## Builder and trust model

The builder takes the Section 16 chain (request through the Prompt 891 implementation request), the Prompt 892 validation result, the Prompt 894 policy and a caller-supplied `approval_request_id`. Eligibility is never taken from the caller. The Prompt 892 context validation re-derives the chain verdict, the supplied 892 result must equal it, and the Prompt 894 builder re-derives the policy from the chain; a supplied policy that differs (a forged but individually valid one) gives `context_mismatch`. Identity and content (`request_id`, `implementation_request_id`, `capability_name`, `operation`, purpose, inputs, outputs, constraints, existing capability) come only from the trusted Prompt 891 request and are copied into fresh objects.

Result: `{status, approval_request, execution_allowed, executed}`, with both flags `False` and `approval_request` set only for `ready_for_approval`.

## Statuses

`ready_for_approval` (the only success), `invalid_request`, `invalid_request_validation`, `invalid_boundary`, `invalid_contract_readiness`, `invalid_policy`, `context_mismatch`, `unsupported_status`, `invalid_approval_request_id`, `approval_request_error`, `validation_error`. No status means that permission or approval was granted.

Mapping: invalid evolution or implementation request -> `invalid_request`; invalid boundary (890) -> `invalid_boundary`; invalid contract readiness (889) -> `invalid_contract_readiness`; any other broken stage of the chain, or a malformed/non-valid 892 result -> `invalid_request_validation`; a policy that is invalid or not `eligible` (ineligible, blocked, unsupported, invalid) -> `invalid_policy`; forged or disagreeing objects -> `context_mismatch`.

## Supported operations

`create` and `improve`. `improve_or_conflict` stays unsupported and yields `unsupported_status`; no approval request is ever built for it.

## Approval request shape and validator

Exactly 17 keys: `version` (int `1`), `approval_request_id`, `request_id`, `implementation_request_id`, `capability_name`, `operation`, `policy_status` (`eligible`), `purpose`, `inputs`, `outputs`, `constraints`, `existing_capability`, `approval_required` (`True`), `implementation_allowed`, `execution_allowed`, `implementation_started`, `executed` (all `False`). The validator enforces exact keys and types, reuses the Prompt 891 validator for the shared fields, and rejects any true permission/start/execution flag, `approval_required=False`, and any extra permission-like field.

## Safety invariants

No filesystem I/O, network, API/model client, subprocess, `exec`/`eval`/`compile`, Memory/AEL/registry mutation, research access, project modification, code or patch generation, installation, automatic approval, execution or self-modification. Inputs are never modified; every call returns fresh objects; results do not depend on time, randomness or environment. No timestamps or UUIDs are generated; `approval_request_id` is caller-supplied.

## Why nothing can start from Prompt 895

The module emits data only. It has no code path that approves, writes, generates, loads or runs anything, and it cannot set `implementation_allowed`, `execution_allowed`, `implementation_started` or `executed` to `True`. Any approval, permission or execution belongs to later, separately specified steps.
