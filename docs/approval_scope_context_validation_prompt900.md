# Approval Scope Context Validation (Prompt 900, Section 17: Controlled Autonomy)

`autonomy/approval_scope_context_validation.py` is a deterministic, read-only **validation
boundary**. It checks that the Prompt 899 approval authority scope is contextually consistent
with the Prompt 895 approval request and the Prompt 896 / 897 approval-decision chain (and,
through them, the Section 16 chain).

**Validating a context is not approving it.** The module grants no approval, creates no
authorization, sets no `implementation_allowed=True` / `execution_allowed=True`, creates no
"approved" state and executes nothing. It generates no code, modifies no project file or
capability, does not self-modify, does not persist, does not touch the filesystem, does not
start a subprocess, does not use the network, does not call an external AI / API and does not
authenticate against any account.

## Public API

```
validate_approval_scope_context(authority_descriptor, scope_descriptor, evolution_request,
    analysis_result, specification, plan, proposal, candidate, readiness_result, design,
    validation_result, blueprint, blueprint_validation_result, contract,
    contract_validation_result, contract_readiness_result, boundary_result,
    implementation_request, request_validation_result, policy, approval_request,
    approval_request_validation_result, decision, decision_validation_result)
validate_approval_scope_context_result(result)
```

Both are deterministic and side-effect free. Nothing supplied is trusted and nothing supplied is
modified or shared with a result.

## Scope semantics

A scope is a boundary, not a grant. `approval_capable` may be `True`, while
`implementation_allowed` and `execution_allowed` must remain `False` in the authority, the scope,
the approval request, the decision and every result.

## Valid path

* Prompt 898 authority descriptor status is `valid`;
* Prompt 899 scope status is `valid` (checked against the authority);
* Prompt 895 approval request is valid and eligible (`policy_status` is `eligible`);
* Prompt 896 decision is valid with `approval_status` exactly `pending_approval`;
* Prompt 897 validation result is `valid` and equals the re-derived one;
* `operation` is exactly `create` or `improve` (never `improve_or_conflict`);
* `approval_required` is `True`; `implementation_allowed`, `execution_allowed`,
  `implementation_started` and `executed` are `False`.

Consistency is verified exactly (type-strict) for `authority_id`, `scope_id`, `capability_name`,
`operation`, `request_id`, `implementation_request_id`, `approval_request_id`, `decision_id`,
`plan_id`, `contract_id`, `boundary_status` and `approval_status`. `scope_id` is the scope's own
identity: it must be a valid label and is copied exactly from the validated scope into the
result (no other trusted object carries one).

## Check order (the first failure decides)

1. authority fails the Prompt 898 validator -> `invalid_authority` (an approval / status concept
   -> `unsupported_status`)
2. scope fails the Prompt 899 context validation -> `invalid_scope` (approval concept or
   `improve_or_conflict` -> `unsupported_status`; scope `authority_id` or `approval_capable`
   differs from the authority -> `context_mismatch`)
3. approval request fails the Prompt 895 validator -> `invalid_approval_request`
4. decision fails the Prompt 896 validator (non-pending `approval_status`, altered flags,
   unexpected fields) -> `invalid_approval_decision`
5. supplied Prompt 897 result malformed or not `valid` -> `invalid_decision_validation`
   (in 3-5, an unexpected key naming an approval concept such as `approved` or
   `authorization`, an approval word as `approval_status` / `status`, or the operation
   `improve_or_conflict` -> `unsupported_status`)
6. Prompt 897 context validation re-derives the chain and does not return `valid`:
   `context_mismatch`, `unsupported_status`, `validation_error`, an invalid approval-request
   validation result -> `invalid_approval_request`, an invalid decision ->
   `invalid_approval_decision`, any other invalid stage (request, Section 16 chain, policy)
   -> `invalid_context`
7. supplied Prompt 897 result differs from the re-derived one (forged identity)
   -> `context_mismatch`
8. identifiers, `capability_name`, `operation`, `plan_id`, `contract_id`, `boundary_status` or
   `approval_status` disagree across the stages -> `context_mismatch`
9. everything holds -> `valid`

Any unexpected internal failure -> `validation_error`.

Statuses (exactly ten): `valid`, `invalid_authority`, `invalid_scope`,
`invalid_approval_request`, `invalid_approval_decision`, `invalid_decision_validation`,
`invalid_context`, `context_mismatch`, `unsupported_status`, `validation_error`. No status
grants approval, authorization, permission or execution.

## Result contract (exactly fifteen keys)

`version`, `status`, `valid`, `authority_id`, `scope_id`, `capability_name`, `operation`,
`request_id`, `implementation_request_id`, `approval_request_id`, `decision_id`, `reason`,
`implementation_allowed`, `execution_allowed`, `executed`.

* `version` is the integer `1`; `valid` is `True` only for `valid`; `reason` equals `status`;
* `implementation_allowed`, `execution_allowed` and `executed` are always `False`;
* the identity fields are filled from the trusted, validated objects only for `valid` and are
  `None` for every other status, so a rejected result never copies untrusted identity values.

`validate_approval_scope_context_result(result)` checks exactly that shape and returns
`{"valid", "errors", "execution_allowed", "executed"}`; it is purely structural and never
raises.

## Tests

`tests/test_approval_scope_context_validation_prompt900.py`.
