# Prompt 897 - Section 17: Approval Decision Validation Boundary

Fourth layer of Section 17 (Controlled Autonomy). New module: `autonomy/implementation_approval_decision_validation.py` (`validate_implementation_approval_decision_context`, `validate_implementation_approval_decision_validation_result`). Deterministic, read-only, side-effect free. No Section 16 module and no Prompt 894, 895 or 896 production module was changed.

## Purpose

Prompt 896 produces a `pending_approval` decision. Prompt 897 validates that such a decision is structurally valid and consistent with the complete trusted chain (Section 16 -> Prompt 892 -> Prompt 894 policy -> Prompt 895 approval request -> Prompt 896 decision). It only answers "is this decision genuine?". It never approves anything and never turns `pending_approval` into approval; there is no `approved` status, no approval field, no authorization, no implementation and no execution.

## Trust model

Nothing supplied is trusted. The Prompt 892 context validation re-derives the chain verdict (reusing the Prompt 876-891 validators and the Prompt 890 boundary), the Prompt 894 builder re-derives the policy, the Prompt 895 builder re-derives the approval request, and the Prompt 896 builder re-derives the decision. A supplied object that differs from the derived one (a forged but individually valid object) gives `context_mismatch`. Identity is also cross-checked across all stages: `request_id`, `implementation_request_id`, `approval_request_id`, `capability_name`, `operation`, `policy_status`, `plan_id`, `contract_id`, `boundary_status` and `approval_status`.

A valid decision has `approval_status == "pending_approval"`, `approval_required == True`, and `implementation_allowed`, `execution_allowed`, `implementation_started` and `executed` all `False`.

## Result contract

Exactly 12 keys: `version` (int `1`), `status`, `valid`, `decision_id`, `request_id`, `implementation_request_id`, `approval_request_id`, `capability_name`, `operation`, `reason` (equals `status`), `execution_allowed` and `executed` (always `False`). `valid` is `True` only for `status == "valid"`. The identity fields are filled from the trusted objects only for `valid`; every other status carries `None`, so a rejected result never repeats forged values.

## Statuses (the complete vocabulary)

| Status | Meaning |
|---|---|
| `valid` | decision is well-formed and consistent with the trusted chain (still only `pending_approval`) |
| `invalid_decision` | decision malformed, wrong version, missing/extra key, non-pending `approval_status`, altered `approval_required`, altered implementation/execution flags or reason |
| `invalid_decision_id` | the only defect is the `decision_id` |
| `invalid_request_validation` | chain (request, 876-890 stages, boundary, readiness), Prompt 892 result or policy is invalid |
| `invalid_approval_request_validation` | Prompt 895 approval request or its validation result is invalid or not valid |
| `context_mismatch` | an object differs from the one derived from the trusted chain, or identity disagrees across stages |
| `unsupported_status` | `improve_or_conflict`, or a valid policy that is not `eligible` (ineligible, blocked, unsupported), or an unsupported operation |
| `validation_error` | unexpected internal failure |

No status grants approval, permission or execution. Checks run in a fixed order and the first failure decides: decision shape, chain, Prompt 892 result, policy, approval request and its validation, decision re-derivation and cross-stage identity, operation.

## Supported operations

`create` and `improve`. `improve_or_conflict` is `unsupported_status` and is never valid.

## Safety invariants

No filesystem I/O, network, API/model client, subprocess, `exec`/`eval`/`compile`, Memory/AEL/registry mutation, persistence, project modification, code or patch generation, approval, authorization, implementation, execution or self-modification. Inputs are never modified; every call returns a fresh object; results do not depend on time, randomness or environment.

## Why nothing is approved

The validator only reads and compares. It has no input that carries an approver and no output that carries an approval, and it cannot set any permission, start or execution flag to `True`. Approval, if it ever exists, belongs to a later, separately specified step.
